# -*- coding: utf-8 -*-
import sys, re, urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://sharousi-kakomon.com"
UA = "Mozilla/5.0 (compatible; sharoushi-kakomon-lab research script; personal study tool)"

WRAPPER_RE = re.compile(r'<div class="q_wrapper">(.*?)</div><!-- /q_wrapper -->', re.DOTALL)
HREF_RE = re.compile(r'<a href="https://sharousi-kakomon\.com/q/\d+/\d+/(\d+)/([a-e])"')
BODY_RE = re.compile(r'<div class="q_body"[^>]*>(.*?)</div>', re.DOTALL)

def strip_tags(s: str) -> str:
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    return s.strip()

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.read().decode("utf-8", errors="replace")

def main():
    year, subject_index, qn = sys.argv[1:4]
    url = f"{BASE}/q/{year}/{subject_index}/{qn}/"
    html = get(url)
    for block in WRAPPER_RE.findall(html):
        href_m = HREF_RE.search(block)
        body_m = BODY_RE.search(block)
        if not (href_m and body_m):
            continue
        print(f"[{href_m.group(1)}-{href_m.group(2).upper()}] {strip_tags(body_m.group(1))}")
        print("---")

if __name__ == "__main__":
    main()
