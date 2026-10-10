#!/usr/bin/env python3
"""맛집 후기 네이버 블로그 발행 도구 (Python + Playwright).

후기 글(review.json)은 Claude Code의 /blog-review 스킬이 사진을 보고 작성한다.
이 스크립트는 사진 정리, 미리보기, 네이버 로그인/발행만 담당한다.

  python blogger.py login                                    # 최초 1회
  python blogger.py prepare --place "성수동 OO갈비" --photos ./photos --memo "..."   # 동영상도 같이 넣으면 됨
  python blogger.py preview output/20261008_231500
  python blogger.py publish output/20261008_231500 [--confirm]
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

import faces
import naver
import phone
import video

register_heif_opener()  # 아이폰 HEIC 사진 지원

MAX_PHOTOS = 20
MAX_SIDE = 1600  # 얼굴 찾기는 이 크기에서 한다
UPLOAD_SIDE = 600  # 올리는 사진의 긴 변 (4:3 사진이면 가로 600x450, 세로 450x600)
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
MAX_VIDEOS = 10  # 네이버 동영상 업로더 한도
ROOT = Path(__file__).parent
# 네이버 한글날 캠페인(행사 1) 필수 태그 — 기간 중 발행하는 후기에 자동으로 붙인다
CAMPAIGN_TAGS = ["네이버한글캠페인", "한글한글아름답게", "나만의한글기록"]
CAMPAIGN_END = datetime(2026, 10, 25, 23, 59, 59)
FOOD_CATEGORY = "73"  # 맛집 카테고리 번호 (이름을 바꾸거나 옮겨도 그대로). 목록: python blogger.py categories
ICLOUD_DRIVE = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
ICLOUD_INBOX = ICLOUD_DRIVE / "블로그 사진"  # 아이폰 '파일' 앱 > iCloud Drive > 블로그 사진


def pick_photos() -> list[Path]:
    """macOS 파일 선택 창(기본 위치: iCloud Drive)으로 사진·동영상을 고른다."""
    start = ICLOUD_DRIVE if ICLOUD_DRIVE.exists() else Path.home() / "Pictures"
    script = f'''
    set fs to choose file with prompt "블로그에 올릴 사진·동영상을 선택하세요 (여러 개: ⌘ 또는 Shift 클릭)" ¬
        of type {{"public.image", "public.movie"}} default location (POSIX file "{start}") with multiple selections allowed
    set out to ""
    repeat with f in fs
        set out to out & POSIX path of f & linefeed
    end repeat
    return out'''
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit("사진 선택이 취소되었습니다.")
    return sorted(Path(line) for line in res.stdout.splitlines() if line.strip())


def take_icloud_photos(dest: Path) -> list[Path]:
    """iCloud Drive '블로그 사진' 폴더의 사진·동영상을 받아 dest로 옮긴다(다음 글에 섞이지 않게 폴더를 비운다)."""
    ICLOUD_INBOX.mkdir(exist_ok=True)
    # 아직 맥에 안 내려온 파일은 '.이름.icloud' 자리표시자로 보인다 → 내려받기 요청 후 대기
    for stub in ICLOUD_INBOX.glob(".*.icloud"):
        subprocess.run(["brctl", "download", str(stub)], capture_output=True)
    for _ in range(600):  # 동영상은 내려받는 데 오래 걸린다
        if not any(ICLOUD_INBOX.glob(".*.icloud")):
            break
        time.sleep(1)
    else:
        sys.exit("iCloud에서 사진을 내려받지 못했습니다 (10분 초과). 잠시 뒤 다시 시도하세요.")
    files = sorted(p for p in ICLOUD_INBOX.iterdir() if p.suffix.lower() in EXTS | VIDEO_EXTS)
    if files:
        dest.mkdir(parents=True)
    return [Path(shutil.move(str(p), dest / p.name)) for p in files]


def map_url(place: str) -> str:
    return "https://map.naver.com/p/search/" + urllib.parse.quote(place)


def cmd_prepare(args):
    """사진을 회전 보정 + 리사이즈 + 얼굴 모자이크해 output/<시각>/01.jpg... 로,
    동영상은 같은 처리를 해 v01.mp4... (+ 장면 캡처 v01-1.jpg...)로 저장하고 review.json 뼈대를 만든다."""
    src = args.photos
    if args.phone:
        files = sorted(phone.receive(ROOT / "inbox" / datetime.now().strftime("%Y%m%d_%H%M%S")))
        if not files:
            sys.exit("휴대폰에서 사진을 받지 못했습니다 (20분 초과).")
    elif args.icloud:
        files = take_icloud_photos(ROOT / "inbox" / datetime.now().strftime("%Y%m%d_%H%M%S"))
        if not files:
            sys.exit(f"iCloud Drive '{ICLOUD_INBOX.name}' 폴더에 사진이 없습니다.")
    elif src is None:
        files = pick_photos()
    elif src.is_dir():
        files = sorted(p for p in src.iterdir() if p.suffix.lower() in EXTS | VIDEO_EXTS)
    else:
        files = [src]
    videos = [f for f in files if f.suffix.lower() in VIDEO_EXTS]
    files = [f for f in files if f.suffix.lower() not in VIDEO_EXTS]
    if not files and not videos:
        sys.exit(f"사진을 찾을 수 없습니다: {src} (지원: {', '.join(sorted(EXTS | VIDEO_EXTS))})")
    if len(files) > MAX_PHOTOS:
        print(f"사진이 {len(files)}장이라 앞의 {MAX_PHOTOS}장만 사용합니다.")
    if len(videos) > MAX_VIDEOS:
        print(f"동영상이 {len(videos)}개라 앞의 {MAX_VIDEOS}개만 사용합니다.")

    out = ROOT / "output" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True)
    names = []
    for i, f in enumerate(files[:MAX_PHOTOS], 1):
        img = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img, n = faces.mosaic_faces(img)  # 다른 사람 얼굴은 항상 모자이크
        if n:
            print(f"  {i:02d}.jpg: 얼굴 {n}개 모자이크")
        img.thumbnail((UPLOAD_SIDE, UPLOAD_SIDE), Image.LANCZOS)
        names.append(f"{i:02d}.jpg")
        img.save(out / names[-1], "JPEG", quality=88)
    video_names = []
    for i, f in enumerate(videos[:MAX_VIDEOS], 1):
        print(f"  동영상 {f.name} 정리 중 (얼굴 모자이크)...", flush=True)
        video_names.append(f"v{i:02d}.mp4")
        hit, thumbs = video.prepare(f, out / video_names[-1])
        print(f"  {video_names[-1]}: " + (f"얼굴 나온 프레임 {hit}개 모자이크" if hit else "얼굴 없음")
              + f", 장면 {', '.join(t.name for t in thumbs)}")

    review = {"place": args.place or "", "memo": args.memo, "photos": names, "videos": video_names,
              "title": "", "blocks": [], "tags": []}
    if args.category:
        review["category"] = args.category
    (out / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


def cmd_preview(folder: Path):
    review = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    names = review["photos"]
    vnames = review.get("videos", [])
    parts = ["<meta charset='utf-8'><body style='max-width:720px;margin:auto;font-family:sans-serif'>",
             f"<h1>{html.escape(review['title'])}</h1>"]
    for b in review["blocks"]:
        if b["type"] == "text":
            parts.append(f"<p>{html.escape(b['text'])}</p>")
        elif b["type"] == "photo" and 0 < b["index"] <= len(names):
            parts.append(f'<p style="text-align:center"><img src="{names[b["index"] - 1]}" style="max-width:100%"/><br/>'
                         f'<small style="color:#888">{html.escape(b.get("caption", ""))}</small></p>')
        elif b["type"] == "video" and 0 < b["index"] <= len(vnames):
            parts.append(f'<p style="text-align:center"><video src="{vnames[b["index"] - 1]}" controls '
                         f'style="max-width:100%"></video><br/>'
                         f'<small style="color:#888">{html.escape(b.get("caption", ""))}</small></p>')
    if review.get("place"):
        parts.append(f'<p>📍 <a href="{map_url(review["place"])}">{html.escape(review["place"])} 네이버 지도</a></p>')
    parts.append(f"<p>태그: {html.escape(', '.join(review.get('tags', [])))}</p>")
    (folder / "preview.html").write_text("\n".join(parts), encoding="utf-8")
    print(folder / "preview.html")


def cmd_publish(folder: Path, confirm: bool):
    blog_id = os.environ.get("NAVER_BLOG_ID") or sys.exit(".env에 NAVER_BLOG_ID를 설정하세요.")
    review = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    if not review["title"] or not review["blocks"]:
        sys.exit("review.json에 제목/본문이 비어 있습니다. 먼저 후기를 작성하세요.")
    photos = [folder / n for n in review["photos"]]
    videos = [folder / n for n in review.get("videos", [])]
    place = review.get("place", "")  # 장소가 있으면 맛집 후기, 없으면 일반 글
    footer = f"📍 {place} 네이버 지도: {map_url(place)}" if place else ""
    tags = review.get("tags", [])
    if place and datetime.now() <= CAMPAIGN_END:
        # 필수 태그가 30개 제한에 잘리지 않게 앞에 둔다
        tags = CAMPAIGN_TAGS + [t for t in tags if t.lstrip("#") not in CAMPAIGN_TAGS]
    category = review.get("category") or os.environ.get("NAVER_CATEGORY", FOOD_CATEGORY)
    print("네이버 블로그에 작성 중... (브라우저 창을 건드리지 마세요)")
    url = naver.publish(blog_id, review["title"], review["blocks"], tags,
                        photos, footer, confirm=confirm, signal_dir=folder, videos=videos,
                        place=place, category=category)
    if url:
        print("완료:", url)


def cmd_add_tags(log_nos: list[str], tags: list[str]):
    blog_id = os.environ.get("NAVER_BLOG_ID") or sys.exit(".env에 NAVER_BLOG_ID를 설정하세요.")
    for n in log_nos:
        added = naver.add_tags(blog_id, n, tags)
        print(f"{n}: " + (f"태그 추가 {', '.join(added)}" if added else "이미 모두 있음"))


def cmd_categories():
    blog_id = os.environ.get("NAVER_BLOG_ID") or sys.exit(".env에 NAVER_BLOG_ID를 설정하세요.")
    req = urllib.request.Request(f"https://m.blog.naver.com/api/blogs/{blog_id}/category-list",
                                 headers={"User-Agent": "Mozilla/5.0", "Referer": f"https://m.blog.naver.com/{blog_id}"})
    cats = json.loads(urllib.request.urlopen(req, timeout=20).read())["result"]["mylogCategoryList"]
    for c in cats:
        if c["divisionLine"]:
            continue
        lock = "" if c["openYN"] else " (비공개)"
        print(f"{c['categoryNo']:>4}  {'  └ ' if c['childCategory'] else ''}{c['categoryName']}{lock}")


def cmd_comment(url: str, text: str, confirm: bool):
    m = re.search(r"blogId=([\w-]+).*?logNo=(\d+)|blog\.naver\.com/([\w-]+)/(\d+)", url)
    if not m:
        sys.exit(f"블로그 글 주소를 알 수 없습니다: {url}")
    blog_id, log_no = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    sig = ROOT / "output"
    sig.mkdir(exist_ok=True)
    if naver.comment(blog_id, log_no, text, confirm=confirm, signal_dir=sig):
        print(f"댓글 등록 완료: https://blog.naver.com/{blog_id}/{log_no}")


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="맛집 후기 네이버 블로그 발행")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="네이버 로그인 (최초 1회)")

    pr = sub.add_parser("prepare", help="사진 정리 + review.json 뼈대 생성")
    pr.add_argument("--place", help="맛집 장소 (예: '성수동 OO갈비'). 생략하면 일반 글(지도·캠페인 태그 없음)")
    pr.add_argument("--category", help="카테고리 번호 (생략하면 맛집 카테고리). 목록: categories")
    pr.add_argument("--photos", type=Path, help="사진·동영상 폴더 또는 파일 (생략하면 선택 창이 열림)")
    pr.add_argument("--phone", action="store_true", help="휴대폰에서 사진 선택 (QR 코드)")
    pr.add_argument("--icloud", action="store_true",
                    help="iCloud Drive '블로그 사진' 폴더의 사진 사용 (외출 중 폰에서 보낼 때)")
    pr.add_argument("--memo", default="", help="직접 겪은 내용 (웨이팅, 추천메뉴, 가격 등)")

    pv = sub.add_parser("preview", help="review.json으로 preview.html 생성")
    pv.add_argument("folder", type=Path)

    pb = sub.add_parser("publish", help="후기 폴더를 네이버 블로그에 발행")
    pb.add_argument("folder", type=Path)
    pb.add_argument("--confirm", action="store_true", help="발행 버튼 누르기 전에 멈춤")

    at = sub.add_parser("add-tags", help="이미 발행한 글에 태그 추가")
    at.add_argument("log_nos", nargs="+", help="글 번호(logNo)")
    at.add_argument("--tags", nargs="+", default=CAMPAIGN_TAGS)

    sub.add_parser("categories", help="내 블로그 카테고리 번호 목록")

    cm = sub.add_parser("comment", help="블로그 글에 댓글 달기 (이벤트 응모 등)")
    cm.add_argument("url", help="글 주소 (https://blog.naver.com/<아이디>/<글번호>)")
    cm.add_argument("--text", required=True, help="댓글 내용 (줄바꿈은 \\n)")
    cm.add_argument("--confirm", action="store_true", help="등록 버튼 누르기 전에 멈춤 (output/.go 로 진행)")

    args = ap.parse_args()
    if args.cmd == "login":
        naver.login()
    elif args.cmd == "prepare":
        cmd_prepare(args)
    elif args.cmd == "preview":
        cmd_preview(args.folder)
    elif args.cmd == "categories":
        cmd_categories()
    elif args.cmd == "comment":
        cmd_comment(args.url, args.text.replace("\\n", "\n"), args.confirm)
    elif args.cmd == "add-tags":
        cmd_add_tags(args.log_nos, args.tags)
    else:
        cmd_publish(args.folder, args.confirm)


if __name__ == "__main__":
    main()
