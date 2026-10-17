"""네이버 블로그 스마트에디터 ONE을 브라우저로 조작해 글을 발행한다.

공식 글쓰기 API가 없어졌기 때문에 사람이 하는 동작(클릭/타이핑/파일 선택)을 그대로 재현한다.
네이버가 에디터 마크업을 바꾸면 아래 셀렉터를 고쳐야 한다.
"""
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path(__file__).parent / ".naver_profile"  # 로그인 쿠키가 저장됨 — 공유 금지

# 스마트에디터 ONE 셀렉터
SEL_TITLE = ".se-documentTitle .se-text-paragraph"
SEL_FIRST_TEXT = ".se-component.se-text .se-text-paragraph"
SEL_COMPONENT = ".se-component:not(.se-documentTitle)"
SEL_IMAGE = ".se-component.se-image"
SEL_ALERT = '.se-popup-alert'  # 업로드 중 뜨는 에디터 알림창
UPLOAD_GAP = 4  # 초. 사진 사이 간격
SEL_UPLOAD_PROGRESS = ".se-popup-progress"
SEL_IMAGE_BTN = "button.se-image-toolbar-button"
SEL_COVER_BTN = ".se-set-rep-image-button"  # 사진 선택 시 왼쪽 위 '대표' 버튼
SEL_AI_MARK = "button.se-set-ai-mark-button-toggle"  # 사진마다 붙는 'AI 활용 설정' 토글
SEL_CAPTION = ".se-caption .se-text-paragraph"
SEL_VIDEO = ".se-component.se-video"
SEL_VIDEO_BTN = "button.se-video-toolbar-button"  # 툴바 '동영상'
SEL_VIDEO_POPUP = ".se-popup-video-upload"
SEL_VIDEO_ADD = SEL_VIDEO_POPUP + ' [data-logcode="lmvup.attmv"]'  # '동영상 추가' (업로드 전후로 클래스가 바뀜)
SEL_VIDEO_STATE = SEL_VIDEO_POPUP + " .nvu_file_item .nvu_state"  # 대기중 → 업로드 진행중 → 대표 이미지 추출중 → 업로드 완료
SEL_VIDEO_TITLE = SEL_VIDEO_POPUP + " #nvu_inp_box_title"  # 필수, 최대 40자. 글에서 동영상 아래 제목으로 보인다
SEL_VIDEO_SUBMIT = SEL_VIDEO_POPUP + " .nvu_btn_submit"
VIDEO_UPLOAD_TIMEOUT = 900  # 초. 큰 동영상은 업로드 + 대표 이미지 추출이 오래 걸린다
SEL_MAP_BTN = "button.se-map-toolbar-button"  # 툴바 '장소'
SEL_MAP_POPUP = ".se-popup-placesMap"
SEL_MAP_INPUT = SEL_MAP_POPUP + " input.react-autosuggest__input"
SEL_MAP_SEARCH = SEL_MAP_POPUP + " .se-place-search-button"
SEL_MAP_RESULT = SEL_MAP_POPUP + " .se-place-map-search-result-item"
SEL_MAP_CONFIRM = SEL_MAP_POPUP + " .se-popup-button-confirm"
SEL_POPUPS = [".se-popup-button-cancel", ".se-help-panel-close-button"]  # 이어쓰기 팝업, 도움말
SEL_PUBLISH = 'button[class*="publish_btn"]'
SEL_TAG_INPUT = 'input[placeholder*="태그"]'
SEL_CONFIRM = 'button[class*="confirm_btn"]'
SEL_CATEGORY_BTN = 'button[class*="selectbox_button"]'  # 발행 창의 카테고리 선택
SEL_CATEGORY_ITEM = 'label[class*="radio_label"]'
SEL_TAG = 'span[class^="tag__"]'  # 발행 창에 이미 달린 태그
# 모바일 댓글(네이버 공통 댓글 모듈 cbox)
SEL_CMT_INPUT = ".u_cbox_write_box .u_cbox_text[contenteditable=true]"
SEL_CMT_SUBMIT = ".u_cbox_write_box .u_cbox_btn_upload"
SEL_CMT_BODY = ".u_cbox_list .u_cbox_contents"


def _mark_clean_exit():
    """지난 실행이 비정상 종료됐어도 '페이지 복원' 팝업이 뜨지 않게 프로필을 정상 종료 상태로 고친다."""
    pref = PROFILE_DIR / "Default" / "Preferences"
    try:
        data = json.loads(pref.read_text(encoding="utf-8"))
        data.setdefault("profile", {})["exit_type"] = "Normal"
        data["profile"]["exited_cleanly"] = True
        pref.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError):
        pass  # 첫 실행이라 파일이 없거나 읽을 수 없으면 그냥 넘어간다


def _launch(p):
    _mark_clean_exit()
    kw = dict(user_data_dir=str(PROFILE_DIR), headless=False, locale="ko-KR",
              viewport={"width": 1280, "height": 900},
              args=["--hide-crash-restore-bubble"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **kw)
    except Exception:
        return p.chromium.launch_persistent_context(**kw)  # 크롬이 없으면 번들 Chromium


def login():
    """최초 1회: 브라우저를 열어 사용자가 직접 로그인한다(자동 로그인은 캡차에 막힘)."""
    with sync_playwright() as p:
        ctx = _launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        print("브라우저에서 네이버에 로그인하세요('로그인 상태 유지' 체크). 로그인되면 자동으로 닫힙니다. (최대 5분)")
        for _ in range(300):
            if any(c["name"] == "NID_AUT" for c in ctx.cookies("https://www.naver.com")):
                break
            time.sleep(1)
        else:
            ctx.close()
            raise SystemExit("5분 안에 로그인이 확인되지 않았습니다. 다시 실행하세요.")
        time.sleep(3)  # 쿠키가 프로필에 기록될 시간
        ctx.close()
    print(f"로그인 정보 저장됨: {PROFILE_DIR}")


def _click_if_present(loc, timeout=2000) -> bool:
    try:
        loc.first.click(timeout=timeout)
        return True
    except PWTimeout:
        return False


def _dismiss_alert(page, ed):
    """에디터 알림창(se-popup-alert)이 떠 있으면 문구를 기록하고 닫는다. 남아 있으면 모든 클릭이 막힌다."""
    alert = ed.locator(SEL_ALERT)
    for _ in range(3):
        if not alert.count() or not alert.first.is_visible():
            return
        text = " ".join(alert.first.inner_text().split())
        print(f"  알림창 닫음: {text[:100]}", flush=True)
        if not (_click_if_present(alert.locator(".se-popup-button-cancel"), 1000)
                or _click_if_present(alert.locator(".se-popup-button-confirm"), 1000)
                or _click_if_present(alert.locator(".se-popup-close-button"), 1000)):
            page.keyboard.press("Escape")
        time.sleep(0.5)


def _focus_end(page, ed):
    """커서를 문서 맨 끝 텍스트 단락으로 옮긴다."""
    _dismiss_alert(page, ed)
    last = ed.locator(SEL_COMPONENT).last
    if "se-text" in (last.get_attribute("class") or ""):
        last.locator(".se-text-paragraph").last.click()
        page.keyboard.press("End")
    else:
        last.click()
        page.keyboard.press("Enter")


def _alert_visible(ed) -> bool:
    alert = ed.locator(SEL_ALERT)
    return bool(alert.count()) and alert.first.is_visible()


def _upload_image(page, ed, path: Path) -> bool:
    """사진을 올리고 실제로 본문에 남았는지까지 확인한다.
    '파일 전송 오류'는 사진 칸이 잠깐 생겼다가 사라지는 식으로 나서, 칸이 생긴 것만으로는 성공이 아니다."""
    before = ed.locator(SEL_IMAGE).count()
    _dismiss_alert(page, ed)
    try:
        with page.expect_file_chooser(timeout=15000) as fc:
            ed.locator(SEL_IMAGE_BTN).first.click()
    except PWTimeout:
        return False
    fc.value.set_files(str(path))
    for _ in range(60):  # 사진 칸이 생길 때까지 (최대 30초)
        if ed.locator(SEL_IMAGE).count() > before or _alert_visible(ed):
            break
        time.sleep(0.5)
    try:
        ed.locator(SEL_UPLOAD_PROGRESS).first.wait_for(state="hidden", timeout=30000)
    except PWTimeout:
        pass
    # 전송 오류 알림은 몇 초 늦게 뜨고 그때 사진 칸이 사라지므로, 잠시 지켜본 뒤에야 성공으로 본다
    failed = False
    for _ in range(16):
        time.sleep(0.5)
        if _alert_visible(ed) or ed.locator(SEL_IMAGE).count() <= before:
            failed = True
            time.sleep(1)
            break
    _dismiss_alert(page, ed)
    if ed.locator(SEL_IMAGE).count() <= before:
        return False
    if failed:  # 깨진 사진 칸이 남아 있으면 지운다
        try:
            ed.locator(SEL_IMAGE).last.click()
            page.keyboard.press("Delete")
            time.sleep(0.5)
        except PWTimeout:
            pass
        return False
    return True


def _insert_image(page, ed, path: Path, caption: str):
    # 짧은 시간에 사진을 많이 올리면 네이버가 '일시적으로 파일전송을 사용할 수 없습니다'를 내므로 쉬었다가 다시 시도한다
    time.sleep(UPLOAD_GAP)  # 연달아 올리면 전송 제한에 걸린다
    for wait in (15, 30, 60, 120, 0):
        if _upload_image(page, ed, path):
            break
        if not wait:
            raise RuntimeError(f"사진 업로드가 계속 실패합니다: {path.name}")
        print(f"  사진 업로드 실패 — {wait}초 뒤 다시 시도: {path.name}", flush=True)
        time.sleep(wait)
        _focus_end(page, ed)
    if caption:
        try:
            img = ed.locator(SEL_IMAGE).last
            img.locator("img.se-image-resource").click()  # 사진을 선택해야 캡션 칸이 보인다
            img.locator(SEL_CAPTION).click(timeout=3000)
            page.keyboard.type(caption)
        except PWTimeout:
            pass  # 캡션 칸을 못 찾으면 생략
    _focus_end(page, ed)


def _insert_video(page, ed, path: Path, title: str):
    """툴바 '동영상' → '동영상 추가'로 파일을 올리고, 업로드가 끝나면 제목을 넣고 '완료'를 누른다."""
    before = ed.locator(SEL_VIDEO).count()
    ed.locator(SEL_VIDEO_BTN).first.click()
    with page.expect_file_chooser() as fc:
        ed.locator(SEL_VIDEO_ADD).first.click()
    fc.value.set_files(str(path))
    state = ed.locator(SEL_VIDEO_STATE).first
    for _ in range(VIDEO_UPLOAD_TIMEOUT // 2):
        text = state.inner_text() if state.count() else ""
        if "완료" in text:
            break
        if "실패" in text or "오류" in text:
            raise RuntimeError(f"동영상 업로드 실패({text}): {path.name}")
        time.sleep(2)
    else:
        raise RuntimeError(f"동영상 업로드가 {VIDEO_UPLOAD_TIMEOUT // 60}분 안에 끝나지 않았습니다: {path.name}")
    ed.locator(SEL_VIDEO_TITLE).fill(title[:40])
    ed.locator(SEL_VIDEO_SUBMIT).click()
    ed.locator(SEL_VIDEO_POPUP).first.wait_for(state="detached", timeout=30000)
    for _ in range(20):
        if ed.locator(SEL_VIDEO).count() > before:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(f"동영상이 본문에 들어가지 않았습니다: {path.name}")
    time.sleep(1)
    _focus_end(page, ed)


def _insert_place(page, ed, place: str) -> bool:
    """툴바 '장소' 버튼으로 네이버 지도를 삽입한다. 검색 결과가 없으면 팝업을 닫고 False."""
    ed.locator(SEL_MAP_BTN).first.click()
    inp = ed.locator(SEL_MAP_INPUT).first
    inp.wait_for(timeout=10000)
    inp.fill(place)  # keyboard.type은 포커스가 본문에 남아 있으면 본문에 써 버린다
    time.sleep(1.5)
    # 자동완성 목록이 검색 버튼 클릭을 가로채므로 닫는다. 단 목록이 없을 때 Escape를 누르면 입력이 지워진다
    if ed.locator(SEL_MAP_POPUP + " .react-autosuggest__suggestion").count():
        page.keyboard.press("Escape")
        time.sleep(0.3)
    if inp.input_value() != place:
        inp.fill(place)
        time.sleep(0.5)
    ed.locator(SEL_MAP_SEARCH + ":not([disabled])").first.click(timeout=10000)
    item = ed.locator(SEL_MAP_RESULT).first
    try:
        item.wait_for(timeout=10000)
    except PWTimeout:
        page.keyboard.press("Escape")  # 자동완성 목록 닫기
        _click_if_present(ed.locator(SEL_MAP_POPUP + " .se-popup-close-button"))
        # 팝업이 남아 있으면 이후 입력(지도 링크)이 검색창으로 들어가므로 여기서 멈춘다
        ed.locator(SEL_MAP_POPUP).first.wait_for(state="detached", timeout=5000)
        _focus_end(page, ed)
        return False
    item.hover()
    item.locator(".se-place-add-button").click()
    ed.locator(SEL_MAP_CONFIRM).first.click()
    ed.locator(SEL_MAP_POPUP).first.wait_for(state="detached", timeout=10000)
    time.sleep(1)
    _focus_end(page, ed)
    return True


def _place_candidates(place: str) -> list[str]:
    """'연희동 새라울'처럼 지역명이 붙어 검색이 안 될 때를 위해 상호명만으로도 찾아본다."""
    words = place.split()
    names = [place, " ".join(words[1:]), words[-1]] if len(words) > 1 else [place]
    return [n for i, n in enumerate(names) if n and n not in names[:i]]


def _set_cover(page, ed):
    """첫 사진을 대표 이미지로 지정한다. 동영상을 올리면 네이버가 영상 썸네일을 대표로 잡을 수 있어서다."""
    img = ed.locator(SEL_IMAGE).first
    if not img.count():
        return
    try:
        img.locator("img.se-image-resource").click()
        btn = img.locator(SEL_COVER_BTN).first
        btn.wait_for(timeout=3000)
        if "se-is-selected" not in (btn.get_attribute("class") or ""):
            btn.click()
        print("  대표 이미지: 첫 사진")
    except PWTimeout:
        print("  대표 이미지 버튼을 못 찾음 — 발행 전 화면에서 확인 필요")
    _focus_end(page, ed)


def _set_ai_marks(page, ed):
    """사진마다 붙는 'AI 활용 설정' 토글을 모두 끈다(사용자 요청: 항상 끔)."""
    imgs = ed.locator(SEL_IMAGE)
    off = 0
    for i in range(imgs.count()):
        img = imgs.nth(i)
        try:
            img.locator("img.se-image-resource").click()
            btn = img.locator(SEL_AI_MARK).first
            btn.wait_for(timeout=3000)
            if "se-is-selected" in (btn.get_attribute("class") or ""):
                btn.click()
            if "se-is-selected" not in (btn.get_attribute("class") or ""):
                off += 1
        except PWTimeout:
            pass
    print(f"  AI 활용 설정 끔: {off}/{imgs.count()}장")
    _focus_end(page, ed)


def _select_category(ed, category: str):
    """발행 창에서 카테고리를 고른다. 숫자면 카테고리 번호(이름을 바꾸거나 옮겨도 그대로), 아니면 이름으로 찾는다.
    못 찾으면 예외를 내서 사용자가 직접 고르게 한다."""
    btn = ed.locator(SEL_CATEGORY_BTN).first
    if category.isdigit():
        if btn.locator(f'[data-testid="categoryItemText_{category}"]').count():
            return
        btn.click()
        item = ed.locator(f'label:has([data-testid="categoryItemText_{category}"])')
    else:
        if btn.inner_text().strip() == category:
            return
        btn.click()
        item = ed.locator(SEL_CATEGORY_ITEM).filter(has_text=re.compile(rf"^\s*{re.escape(category)}\s*$"))
    if item.count() == 0:
        raise RuntimeError(f"카테고리 '{category}'를 찾지 못했습니다")
    item.first.click()


def _open_editor(page):
    """글쓰기/수정 화면은 iframe#mainFrame 안에 열리기도 하고 바로 열리기도 한다."""
    try:
        page.wait_for_selector("iframe#mainFrame", timeout=8000)
        ed = page.frame_locator("iframe#mainFrame")
    except PWTimeout:
        ed = page
    ed.locator(SEL_TITLE).first.wait_for(timeout=30000)
    for sel in SEL_POPUPS:
        _click_if_present(ed.locator(sel))
    return ed


def add_tags(blog_id: str, log_no: str, tags: list[str]) -> list[str]:
    """이미 발행한 글을 수정 화면에서 열어 빠진 태그만 추가하고 다시 발행한다. 본문·카테고리는 건드리지 않는다.
    추가한 태그 목록을 돌려준다(이미 다 있으면 저장하지 않고 빈 목록)."""
    with sync_playwright() as p:
        ctx = _launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(f"https://blog.naver.com/PostUpdateForm.naver?blogId={blog_id}&logNo={log_no}")
            if "nid.naver.com" in page.url:
                raise SystemExit("네이버 로그인이 필요합니다: python blogger.py login")
            ed = _open_editor(page)
            ed.locator(SEL_PUBLISH).first.click()
            tag_input = ed.locator(SEL_TAG_INPUT).first
            tag_input.wait_for(timeout=10000)
            have = {t.strip().lstrip("#") for t in ed.locator(SEL_TAG).all_inner_texts()}
            missing = [t.lstrip("#") for t in tags if t.lstrip("#") not in have]
            if len(have) + len(missing) > 30:
                raise RuntimeError(f"태그가 30개를 넘습니다 (기존 {len(have)}개 + 추가 {len(missing)}개)")
            if not missing:
                return []
            for t in missing:
                tag_input.click()
                page.keyboard.type(t)
                page.keyboard.press("Enter")
            ed.locator(SEL_CONFIRM).first.click()
            # 저장되면 글 보기로 이동한다(보기 화면에도 같은 제목 클래스가 있어 URL로 판단)
            page.wait_for_url(lambda u: "PostUpdateForm" not in u, timeout=60000)
            return missing
        finally:
            ctx.close()


def comment(blog_id: str, log_no: str, text: str, confirm: bool = False,
            signal_dir: Path | None = None) -> bool:
    """남의 글(이벤트 글 등)에 내 계정으로 댓글을 단다. 등록이 확인되면 True."""
    with sync_playwright() as p:
        ctx = _launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(f"https://m.blog.naver.com/CommentList.naver?blogId={blog_id}&logNo={log_no}")
            if "nid.naver.com" in page.url:
                raise SystemExit("네이버 로그인이 필요합니다: python blogger.py login")
            box = page.locator(SEL_CMT_INPUT).first
            box.wait_for(timeout=15000)
            # '댓글을 입력해주세요.' 안내 문구가 입력칸을 덮고 있어 그걸 눌러야 입력칸이 열린다
            if not _click_if_present(page.locator(".u_cbox_write_box .u_cbox_guide")):
                box.click()
            for i, line in enumerate(text.split("\n")):
                if i:
                    page.keyboard.press("Shift+Enter")
                page.keyboard.type(line)
            if confirm:
                sig = signal_dir or Path.cwd()
                page.screenshot(path=str(sig / "comment_confirm.png"))
                if not _wait_confirm(sig):
                    print("댓글 등록을 취소했습니다.")
                    return False
            page.locator(SEL_CMT_SUBMIT).first.click()
            # 등록되면 입력칸이 비고 목록에 내 댓글이 나타난다
            first_line = text.split("\n")[0].strip()[:30]
            page.locator(SEL_CMT_BODY, has_text=first_line).first.wait_for(timeout=15000)
            return True
        finally:
            ctx.close()


def _wait_confirm(signal_dir: Path) -> bool:
    """발행 직전 확인. 터미널이면 Enter, 아니면(Claude Code 실행) 신호 파일 .go / .cancel 을 기다린다."""
    if sys.stdin.isatty():
        try:
            input("브라우저에서 글을 확인하세요. Enter를 누르면 발행합니다 (중단: Ctrl+C) ")
            return True
        except KeyboardInterrupt:
            return False
    go, cancel = signal_dir / ".go", signal_dir / ".cancel"
    for f in (go, cancel):
        f.unlink(missing_ok=True)
    print(f"CONFIRM_WAIT: 브라우저에서 확인 후 발행하려면 {go} / 취소하려면 {cancel} 파일을 만드세요.", flush=True)
    while not (go.exists() or cancel.exists()):
        time.sleep(1)
    ok = go.exists()
    for f in (go, cancel):
        f.unlink(missing_ok=True)
    return ok


def _wait_post_url(page, blog_id: str, title: str, timeout: int = 60) -> str:
    """발행 후 주소에 글 번호(logNo)가 생길 때까지 기다려 글 주소를 돌려준다."""
    for _ in range(timeout * 2):
        m = re.search(r"logNo=(\d+)", page.url) or re.search(rf"blog\.naver\.com/{blog_id}/(\d+)", page.url)
        if m:
            return f"https://blog.naver.com/{blog_id}/{m.group(1)}"
        time.sleep(0.5)
    raise RuntimeError("발행 후 글 주소를 찾지 못했습니다(발행은 됐을 수 있으니 블로그에서 확인하세요)")


def publish(blog_id: str, title: str, blocks: list[dict], tags: list[str],
            photos: list[Path], footer: str, confirm: bool = False,
            signal_dir: Path | None = None, place: str = "", category: str = "",
            videos: list[Path] | None = None) -> str:
    videos = videos or []
    with sync_playwright() as p:
        ctx = _launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://blog.naver.com/{blog_id}?Redirect=Write&")
        if "nid.naver.com" in page.url:
            ctx.close()
            raise SystemExit("네이버 로그인이 필요합니다: python blogger.py login")

        try:
            page.wait_for_selector("iframe#mainFrame", timeout=15000)
            ed = page.frame_locator("iframe#mainFrame")
        except PWTimeout:
            ed = page  # 에디터가 iframe 없이 열리는 경우

        try:
            ed.locator(SEL_TITLE).first.wait_for(timeout=30000)
            for sel in SEL_POPUPS:
                _click_if_present(ed.locator(sel))

            ed.locator(SEL_TITLE).first.click()
            page.keyboard.type(title)
            ed.locator(SEL_FIRST_TEXT).first.click()

            for b in blocks:
                if b["type"] == "text":
                    page.keyboard.type(b["text"])
                    page.keyboard.press("Enter")
                    page.keyboard.press("Enter")
                elif b["type"] == "photo" and 0 < b["index"] <= len(photos):
                    _insert_image(page, ed, photos[b["index"] - 1], b.get("caption", ""))
                    print(f"  사진 {b['index']} 삽입")
                elif b["type"] == "video" and 0 < b["index"] <= len(videos):
                    print(f"  동영상 {b['index']} 업로드 중...", flush=True)
                    _insert_video(page, ed, videos[b["index"] - 1], b.get("caption") or place or title)
                    print(f"  동영상 {b['index']} 삽입")
            n_img = ed.locator(SEL_IMAGE).count()
            n_photo = sum(1 for b in blocks if b["type"] == "photo" and 0 < b["index"] <= len(photos))
            print(f"  본문 사진 {n_img}/{n_photo}장", flush=True)
            if n_img != n_photo:
                raise RuntimeError(f"본문 사진 수가 맞지 않습니다({n_img}/{n_photo}장)")
            placed = ""
            for name in _place_candidates(place):
                if _insert_place(page, ed, name):
                    placed = name
                    break
            if placed:
                print(f"  지도 삽입: {placed}")
            else:
                page.keyboard.type(footer)  # 장소 검색 실패 시 지도 링크로 대신한다
            _set_cover(page, ed)
            _set_ai_marks(page, ed)

            if confirm:
                # 원격(휴대폰)에서도 확인할 수 있게 발행 직전 화면을 저장한다
                page.screenshot(path=str((signal_dir or Path.cwd()) / "confirm.png"), full_page=True)
            if confirm and not _wait_confirm(signal_dir or Path.cwd()):
                print("발행을 취소했습니다. (작성 중인 글은 네이버 임시저장에 남을 수 있습니다)")
                ctx.close()
                return ""

            ed.locator(SEL_PUBLISH).first.click()
            tag_input = ed.locator(SEL_TAG_INPUT).first
            tag_input.wait_for(timeout=10000)
            if category:
                _select_category(ed, category)
            for t in tags[:30]:  # 네이버 태그 최대 30개
                tag_input.click()
                page.keyboard.type(t.lstrip("#"))
                page.keyboard.press("Enter")
            ed.locator(SEL_CONFIRM).first.click()

            # 발행 후 글 보기 화면도 같은 제목 마크업을 써서, 에디터가 사라지는 대신 주소에 글 번호가 생기길 기다린다
            url = _wait_post_url(page, blog_id, title)
        except Exception as e:
            print(f"\nSTOPPED: 자동 작성 중 멈췄습니다: {e}", flush=True)
            print("브라우저를 열어둡니다. 직접 마무리(발행)한 뒤 브라우저 창을 닫으세요.", flush=True)
            url = page.url
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
        ctx.close()
        return url
