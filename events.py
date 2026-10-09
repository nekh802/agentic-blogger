#!/usr/bin/env python3
"""네이버 블로그 공식 블로그(blogpeople)의 '블로그 이벤트' 카테고리에서 새 글을 가져온다.

  python events.py          # 처음 보는 이벤트 글의 제목·주소·본문을 출력하고 '본 글'로 기록
  python events.py --peek   # 기록하지 않고 출력만

응모는 하지 않는다. Claude가 출력을 읽고 응모 방법을 정리해 사용자 승인을 받는다.
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BLOG_ID = "blogpeople"
CATEGORY_NO = 21  # 블로그 이벤트 (하위 '깜짝 이벤트' 포함)
SEEN_FILE = Path(__file__).parent / "events_seen.json"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def recent_posts(count: int = 15) -> list[dict]:
    raw = _get(f"https://blog.naver.com/PostTitleListAsync.naver?blogId={BLOG_ID}&currentPage=1"
               f"&categoryNo={CATEGORY_NO}&parentCategoryNo={CATEGORY_NO}&countPerPage={count}")
    data = json.loads(raw.replace("\\'", "'"), strict=False)  # 네이버 응답에 잘못된 \' 이스케이프가 섞여 온다
    return [{"logNo": p["logNo"], "date": p["addDate"],
             "title": html.unescape(urllib.parse.unquote_plus(p["title"]))} for p in data["postList"]]


def post_text(log_no: str) -> str:
    s = _get(f"https://m.blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}")
    s = s[s.find("se-main-container"):]
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", s)).replace("​", "")
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:6000]


def main():
    peek = "--peek" in sys.argv
    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    new = [p for p in recent_posts() if p["logNo"] not in seen]
    if not new:
        print("NO_NEW_EVENTS")
        return
    for p in new:
        print(f"=== {p['date']} {p['title']}")
        print(f"https://blog.naver.com/{BLOG_ID}/{p['logNo']}")
        print(post_text(p["logNo"]))
        print()
    if not peek:
        SEEN_FILE.write_text(json.dumps(sorted(seen | {p["logNo"] for p in new})))


if __name__ == "__main__":
    main()
