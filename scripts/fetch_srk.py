#!/usr/bin/env python3
"""
社労士過去問ランド (sharousi-kakomon.com) から、指定した年度・科目の
「肢別」問題文と正誤（○/×）だけを取得してJSONに変換するスクリプト。

取得するのは実施団体（全国社会保険労務士会連合会）が作成した試験問題の
文言と正誤のみ。社労士過去問ランド独自の「ポイント/解説/出題根拠/正解率」は
そのサイト固有の著作物であるため、意図的に取得・保存しない。
解説は当サイトが別途、条文等の一次情報を基に自作する前提。

肢（A〜E）を1つの独立した○×問題として扱い、既存のapp.js/index.htmlの
「5択から1つ選ぶ」UIをそのまま流用できる形（choices=[○,×]）で出力する。

使い方:
    python fetch_srk.py <year> <subject_index> <subject_official_name> <out_path>

例:
    python fetch_srk.py 2025 0 "労働基準法及び労働安全衛生法" ../data/r7-labor.json
"""
import sys
import re
import json
import time
import urllib.request
import http.cookiejar

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

BASE = "https://sharousi-kakomon.com"
UA = "Mozilla/5.0 (compatible; sharoushi-kakomon-lab research script; personal study tool)"
SLEEP_SEC = 0.7  # サーバーに配慮した間隔


def build_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    return opener


def get(opener, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=15) as res:
        return res.read().decode("utf-8", errors="replace")


def post_check(opener, referer_url, q_id):
    data = f"q={q_id}&a=1".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/q/check_q_a.php",
        data=data,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer_url,
        },
    )
    with opener.open(req, timeout=15) as res:
        return res.read().decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    return s.strip()


WRAPPER_RE = re.compile(r'<div class="q_wrapper">(.*?)</div><!-- /q_wrapper -->', re.DOTALL)
HREF_RE = re.compile(r'<a href="https://sharousi-kakomon\.com/q/\d+/\d+/(\d+)/([a-e])"')
BODY_RE = re.compile(r'<div class="q_body"[^>]*>(.*?)</div>', re.DOTALL)
ANSWER_ID_RE = re.compile(r"answer\((\d+),")


def parse_question_page(html: str):
    """1問分のページ(肢A〜E)をパースして [{number, letter, text, q_id}, ...] を返す"""
    items = []
    for block in WRAPPER_RE.findall(html):
        href_m = HREF_RE.search(block)
        body_m = BODY_RE.search(block)
        id_m = ANSWER_ID_RE.search(block)
        if not (href_m and body_m and id_m):
            continue
        items.append({
            "number": int(href_m.group(1)),
            "letter": href_m.group(2),
            "text": strip_tags(body_m.group(1)),
            "q_id": id_m.group(1),
        })
    return items


TRUE_FALSE_RE = re.compile(r"この肢は(正しい|誤り)")


def fetch_true_answer(opener, referer_url, q_id, debug=False):
    resp = post_check(opener, referer_url, q_id)
    m = TRUE_FALSE_RE.search(resp)
    if not m:
        if debug:
            print(f"    [debug] q_id={q_id} 応答先頭200字: {resp[:200]!r}", file=sys.stderr)
        return None
    return m.group(1) == "正しい"


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    year, subject_index, subject_official, out_path = sys.argv[1:5]
    opener = build_opener()

    list_url = f"{BASE}/q/{year}/{subject_index}/"
    list_html = get(opener, list_url)

    # 問題番号の一覧を取得（例: /q/2025/0/1/ のリンクから）
    q_numbers = sorted(set(
        int(n) for n in re.findall(rf'/q/{year}/{subject_index}/(\d+)/"', list_html)
    ))
    print(f"{len(q_numbers)}問を検出: {q_numbers}", file=sys.stderr)

    out = []
    for qn in q_numbers:
        page_url = f"{BASE}/q/{year}/{subject_index}/{qn}/"
        try:
            html = get(opener, page_url)
        except Exception as e:
            print(f"問{qn}: ページ取得失敗 ({e})", file=sys.stderr)
            continue
        time.sleep(SLEEP_SEC)

        parsed_items = parse_question_page(html)
        if not parsed_items:
            print(f"問{qn}: 肢を検出できず（HTML構造が想定と異なる可能性）", file=sys.stderr)

        for item in parsed_items:
            true_answer = fetch_true_answer(opener, page_url, item["q_id"], debug=True)
            time.sleep(SLEEP_SEC)
            if true_answer is None:
                print(f"警告: 正誤を取得できず q_id={item['q_id']}", file=sys.stderr)
                continue

            out.append({
                "id": f"r{year}-s{subject_index}-{item['number']:03d}{item['letter']}",
                "exam": f"r{year}-s{subject_index}",
                "number": f"問{item['number']}-{item['letter'].upper()}",
                "subject": subject_official,
                "text": item["text"],
                "choices": [
                    {"num": 1, "text": "○ 正しい"},
                    {"num": 2, "text": "× 誤り"},
                ],
                "answer": 1 if true_answer else 2,
                "explanation": None,
                "related_articles": [],
                "source": "全国社会保険労務士会連合会 社会保険労務士試験（社労士過去問ランドの肢別分解に基づき当サイトで再構成。解説は未収録・自社作成予定）",
            })
            print(f"  問{item['number']}-{item['letter'].upper()}: {'○' if true_answer else '×'} 取得完了", file=sys.stderr)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"{len(out)}肢を書き出しました -> {out_path}")


if __name__ == "__main__":
    main()
