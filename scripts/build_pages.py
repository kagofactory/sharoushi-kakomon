#!/usr/bin/env python3
"""
data/*.json から、問題1件ごとに静的HTMLページを生成するビルドスクリプト。

目的: 今までは1枚のindex.html内でJavaScriptがデータを読み込む方式だったため、
検索エンジンから見ると「どの年度・どの問題を検索しても同じURL」という状態だった。
これでは「社労士 過去問 令和7年 労働基準法 問1」のようなロングテール検索から
個別の問題ページへ直接誘導できない。

このスクリプトは、各問題を検索エンジンがそのままインデックスできる実体のある
HTMLファイルとして書き出す（問題文・選択肢・正解・解説・法改正ステータスを
サーバーサイドで完結した形で埋め込み、JavaScriptなしで内容が読める）。
あわせて演習アプリ（index.html）への導線も張る。

sample.json（デモ用）はnoindexにして、実データのみを検索対象にする。

使い方:
    python build_pages.py
    (data/exams.json を読み、data/*.json を全て処理して q/ 以下に出力する)
"""
import json
import re
import glob
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

SITE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(SITE_ROOT, "data")
OUT_DIR = os.path.join(SITE_ROOT, "q")
SUBJECTS_OUT_DIR = os.path.join(SITE_ROOT, "subjects")
SITE_URL = "https://sharoushi-kakomon-lab.example"  # 実際のドメイン取得後に置き換える

# 科目インデックス（rYYYY-sN の N）は全10年度で共通であることを確認済み（CLAUDE.md参照）
SUBJECT_META = [
    ("s0", "労働基準法及び労働安全衛生法"),
    ("s1", "労働者災害補償保険法（徴収法含む）"),
    ("s2", "雇用保険法（徴収法含む）"),
    ("s3", "一般常識（労働に関する一般常識・社会保険に関する一般常識）"),
    ("s4", "健康保険法"),
    ("s5", "厚生年金保険法"),
    ("s6", "国民年金法"),
]

LAW_STATUS_LABEL = {
    "valid": "現行法で有効",
    "amended": "法改正により内容が変更",
    "repealed": "法改正により成立しない設問",
    "unverified": "現行法との照合が未確認",
}

REVIEW_STATUS_LABEL = {
    "ai_unreviewed": "AI生成・専門家未レビュー",
    "expert_reviewed": "社労士レビュー済み",
}

CONTACT_EMAIL = "contact@sharoushi-kakomon-lab.example"  # ドメイン取得後、実際の連絡先に置き換える


def esc(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def slug_of(item_id, exam_id):
    """id から exam_id の接頭辞を取り除いたものをファイル名に使う"""
    if item_id.startswith(exam_id + "-"):
        return item_id[len(exam_id) + 1:]
    return item_id


def render_choice(c, answer_num):
    is_correct = c["num"] == answer_num
    cls = "choice correct" if is_correct else "choice"
    mark = " ✓" if is_correct else ""
    return f'<li class="{cls}">{esc(c["text"])}{mark}</li>'


def render_law_status(item):
    status = item.get("law_status")
    if not status:
        return ""
    label = LAW_STATUS_LABEL.get(status, status)
    note = item.get("law_status_note", "")
    return f'''
    <div class="law-status law-status--{esc(status)}">
      <strong>{esc(label)}</strong>{("　" + esc(note)) if note else ""}
    </div>'''


def render_review_status(item):
    status = item.get("review_status")
    if not status:
        return ""
    label = REVIEW_STATUS_LABEL.get(status, status)
    verified = item.get("last_verified", "")
    subject = f"誤りの報告：{item['id']}"
    body = f"問題ID: {item['id']}%0A指摘内容:%0A"
    mailto = f"mailto:{CONTACT_EMAIL}?subject={subject}&body={body}"
    return f'''
    <div class="review-status">
      <span class="review-badge review-badge--{esc(status)}">{esc(label)}{f"（{esc(verified)}時点）" if verified else ""}</span>
      <a class="report-link" href="{mailto}">誤りを報告する</a>
    </div>'''


def render_explanation(item):
    exp = item.get("explanation")
    if not exp:
        return '<p class="q-pending">解説は準備中です。</p>'
    ref_date = item.get("law_reference_date")
    exp_text = esc(exp) + (f"<br><small>（法令基準日: {esc(ref_date)}）</small>" if ref_date else "")

    articles = item.get("related_articles") or []
    lis = "".join(f"<li>{esc(a)}</li>" for a in articles)
    note = item.get("verification_note")
    if note:
        lis += f'<li class="verification-note">{esc(note)}</li>'
    articles_html = f'<ul class="articles">{lis}</ul>' if lis else ""

    return f'<p>{exp_text}</p>{articles_html}'


PAGE_TMPL = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
{robots_tag}
<link rel="stylesheet" href="{css_path}">
<script type="application/ld+json">
{jsonld}
</script>
</head>
<body>

<header class="site-header">
  <h1><a href="{root_path}index.html">社労士過去問ラボ</a></h1>
  <nav class="site-nav"><a href="{root_path}topics.html">法改正・白書対策</a></nav>
</header>

<main>
  <nav class="breadcrumb">
    <a href="{root_path}index.html">トップ</a> &gt;
    <a href="{exam_index}">{exam_label}</a> &gt;
    {number}
  </nav>

  <div class="card">
    <div class="q-meta">
      <span class="badge">{subject}</span>
      <span class="q-number-label">{number}</span>
    </div>
    <p class="q-text">{text}</p>

    <ul class="choices-static">
      {choices_html}
    </ul>
{law_status_html}
    <div class="explanation">
      <h3>解説</h3>
      {explanation_html}
    </div>
{review_status_html}
    <p class="source-note">出典: {source}</p>
  </div>

  <div class="card note-card">
    <p>
      解説は<b>AI（生成AI）が条文・通達等をもとに作成した下書きで、社会保険労務士など専門家によるレビューを
      経ていません。</b>内容の正確性を保証するものではなく、法的助言でもありません。
      誤りに気づいた場合は上の「誤りを報告する」からご連絡ください。
      <b>本サイトは受験対策のための学習教材であり、個別の労務相談・法的助言を行うものではありません。</b>
      実際の労務管理・手続きについては、社会保険労務士等の専門家にご相談ください。
    </p>
  </div>

  <p class="q-actions">
    <a class="btn-primary" href="{root_path}index.html">この年度・科目を演習する →</a>
  </p>
</main>

<footer class="site-footer">
  <p>出典: 社会保険労務士試験オフィシャルサイト（全国社会保険労務士会連合会 試験センター）／ 非公式の個人学習用サイトです。解説は独自作成・専門家未レビュー。</p>
  <p class="footer-links"><a href="{root_path}terms.html">利用規約</a> ・ <a href="{root_path}privacy.html">プライバシーポリシー</a></p>
</footer>

</body>
</html>
"""


def build_question_page(item, exam_label, noindex=False):
    choices_html = "\n      ".join(
        render_choice(c, item["answer"]) for c in item["choices"]
    )
    plain_text = re.sub(r"\s+", " ", item["text"]).strip()
    description = (plain_text[:110] + "…") if len(plain_text) > 110 else plain_text

    canonical = f"{SITE_URL}/q/{item['exam']}/{slug_of(item['id'], item['exam'])}.html"

    jsonld = {
        "@context": "https://schema.org",
        "@type": "QAPage",
        "mainEntity": {
            "@type": "Question",
            "name": plain_text,
            "text": plain_text,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": item.get("explanation") or "解説準備中",
            },
        },
    }

    return PAGE_TMPL.format(
        title=f"{esc(item['subject'])} {esc(item['number'])}｜社労士過去問 {esc(exam_label)} - 社労士過去問ラボ",
        description=esc(description),
        canonical=canonical,
        robots_tag='<meta name="robots" content="noindex">' if noindex else "",
        css_path="../../css/style.css",
        jsonld=json.dumps(jsonld, ensure_ascii=False, indent=2),
        root_path="../../",
        exam_index="index.html",
        exam_label=esc(exam_label),
        number=esc(item["number"]),
        subject=esc(item["subject"]),
        text=esc(item["text"]),
        choices_html=choices_html,
        law_status_html=render_law_status(item),
        explanation_html=render_explanation(item),
        review_status_html=render_review_status(item),
        source=esc(item.get("source", "")),
    )


INDEX_TMPL = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{exam_label}｜社労士過去問ラボ</title>
<meta name="description" content="{exam_label}の過去問一覧。問題ごとに解説・法改正ステータス付きで確認できます。">
<link rel="stylesheet" href="../../css/style.css">
</head>
<body>
<header class="site-header">
  <h1><a href="../../index.html">社労士過去問ラボ</a></h1>
  <nav class="site-nav"><a href="../../topics.html">法改正・白書対策</a></nav>
</header>
<main>
  <div class="card">
    <h2>{exam_label}</h2>
    <ul class="question-list">
      {items_html}
    </ul>
  </div>
</main>
<footer class="site-footer">
  <p>非公式の個人学習用サイトです。</p>
  <p class="footer-links"><a href="../../terms.html">利用規約</a> ・ <a href="../../privacy.html">プライバシーポリシー</a></p>
</footer>
</body>
</html>
"""


def build_exam_index(exam_id, exam_label, items):
    lis = "\n      ".join(
        f'<li><a href="{slug_of(it["id"], exam_id)}.html">{esc(it["number"])} {esc(it["subject"])}</a></li>'
        for it in items
    )
    return INDEX_TMPL.format(exam_label=esc(exam_label), items_html=lis)


SUBJECT_TMPL = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{subject_name}の過去問一覧｜社労士過去問ラボ</title>
<meta name="description" content="社労士試験「{subject_name}」の過去問を年度別に一覧。{year_count}年度分・{total_items}肢を収録。年度ごとに問題を見る、または演習を始めることができます。">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="../css/style.css">
</head>
<body>
<header class="site-header">
  <h1><a href="../index.html">社労士過去問ラボ</a></h1>
  <nav class="site-nav"><a href="../topics.html">法改正・白書対策</a></nav>
</header>
<main>
  <nav class="breadcrumb"><a href="../index.html">トップ</a> &gt; {subject_name}</nav>
  <div class="card">
    <h2>{subject_name}</h2>
    <p class="source-note">{year_count}年度分・{total_items}肢を収録</p>
    <ul class="question-list subject-year-list">
      {rows_html}
    </ul>
  </div>
</main>
<footer class="site-footer">
  <p>非公式の個人学習用サイトです。</p>
  <p class="footer-links"><a href="../terms.html">利用規約</a> ・ <a href="../privacy.html">プライバシーポリシー</a></p>
</footer>
</body>
</html>
"""


def build_subject_page(subject_key, subject_name, rows):
    total_items = sum(r["item_count"] for r in rows)
    row_lis = "\n      ".join(
        f'<li class="subject-year-row">'
        f'<span class="subject-year-label">{esc(r["year_label"])}（{r["item_count"]}肢）</span>'
        f'<a class="btn-secondary" href="../q/{r["exam_id"]}/index.html">問題を見る</a>'
        f'<a class="btn-primary" href="../index.html?exam={r["file"]}&mode=single&autostart=1">肢別で解く →</a>'
        f'<a class="btn-primary" href="../index.html?exam={r["file"]}&mode=group&autostart=1">5択で解く →</a>'
        f'</li>'
        for r in rows
    )
    return SUBJECT_TMPL.format(
        subject_name=esc(subject_name),
        year_count=len(rows),
        total_items=total_items,
        canonical=f"{SITE_URL}/subjects/{subject_key}.html",
        rows_html=row_lis,
    )


def main():
    exams_path = os.path.join(DATA_DIR, "exams.json")
    with open(exams_path, encoding="utf-8") as f:
        exams = json.load(f)

    sitemap_urls = [f"{SITE_URL}/index.html", f"{SITE_URL}/topics.html"]
    subject_rows = defaultdict(list)  # "sN" -> [{exam_id, year_label, item_count, file}]

    for exam in exams:
        exam_id = exam["id"]
        is_sample = exam_id == "sample"
        data_path = os.path.join(SITE_ROOT, exam["file"])
        with open(data_path, encoding="utf-8") as f:
            items = json.load(f)

        exam_out_dir = os.path.join(OUT_DIR, exam_id)
        os.makedirs(exam_out_dir, exist_ok=True)

        for item in items:
            html = build_question_page(item, exam["label"], noindex=is_sample)
            out_path = os.path.join(exam_out_dir, f"{slug_of(item['id'], exam_id)}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)
            if not is_sample:
                sitemap_urls.append(f"{SITE_URL}/q/{exam_id}/{slug_of(item['id'], exam_id)}.html")

        index_html = build_exam_index(exam_id, exam["label"], items)
        with open(os.path.join(exam_out_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(index_html)
        if not is_sample:
            sitemap_urls.append(f"{SITE_URL}/q/{exam_id}/index.html")

        print(f"{exam_id}: {len(items)}ページ生成{'（noindex）' if is_sample else ''}")

        if not is_sample:
            m_round = re.match(r"^(第\d+回（[^）]+）)", exam["label"])
            year_label = m_round.group(1) if m_round else exam_id
            m_s = re.search(r"-(s\d)$", exam_id)
            if m_s:
                subject_rows[m_s.group(1)].append({
                    "exam_id": exam_id,
                    "year_label": year_label,
                    "item_count": len(items),
                    "file": exam["file"],
                })

    # 科目別カテゴリページ（subjects/sN.html）
    os.makedirs(SUBJECTS_OUT_DIR, exist_ok=True)
    for subject_key, subject_name in SUBJECT_META:
        rows = sorted(subject_rows.get(subject_key, []), key=lambda r: r["exam_id"], reverse=True)
        html = build_subject_page(subject_key, subject_name, rows)
        with open(os.path.join(SUBJECTS_OUT_DIR, f"{subject_key}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        sitemap_urls.append(f"{SITE_URL}/subjects/{subject_key}.html")
        total_items = sum(r["item_count"] for r in rows)
        print(f"subjects/{subject_key}.html: {subject_name}（{len(rows)}年度・{total_items}肢）")

    # sitemap.xml
    urlset = "\n".join(f"  <url><loc>{u}</loc></url>" for u in sitemap_urls)
    sitemap = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urlset}\n</urlset>\n'
    with open(os.path.join(SITE_ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap)

    # robots.txt
    robots = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    with open(os.path.join(SITE_ROOT, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(robots)

    print(f"\nsitemap.xml: {len(sitemap_urls)}件のURL")
    print("robots.txt を書き出しました")
    print(f"\n※ SITE_URL は仮の値です。実際のドメイン取得後、このスクリプト冒頭の SITE_URL 定数を書き換えて再実行してください。")


if __name__ == "__main__":
    main()
