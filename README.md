# 대신 블로거

맛집 사진과 장소를 주면 후기를 써서 네이버 블로그에 발행합니다. **Anthropic API 키가 필요 없습니다.**

- **후기 작성**: Claude Code가 사진을 직접 보고 씁니다 ([.claude/skills/blog-review/SKILL.md](.claude/skills/blog-review/SKILL.md)).
- **발행**: Python + Playwright가 설치된 크롬으로 네이버 에디터에 입력하고 발행합니다. 네이버 공식 글쓰기 API가 없어져서 사람이 하는 동작을 그대로 재현합니다.

## 설치 (최초 1회)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # NAVER_BLOG_ID 입력
.venv/bin/python blogger.py login   # 열린 크롬에서 직접 로그인 ('로그인 상태 유지' 체크) 후 Enter
```

크롬이 없으면 `.venv/bin/playwright install chromium` 도 실행하세요.

## 사용

이 폴더에서 Claude Code를 열고 이렇게 말하면 됩니다.

```
/blog-review 성수동 OO갈비, 사진은 ~/Desktop/갈비, 웨이팅 30분 / 갈빗살 강추 / 2인 6만원
```

Claude Code가 사진 정리 → 사진 보기 → 후기 작성 → 미리보기 → (확인 후) 발행까지 진행합니다.

사진 경로를 말하지 않으면 iCloud Drive가 열린 파일 선택 창이 뜹니다. ⌘ 또는 Shift를 누른 채 여러 장을 고르세요. 아이폰 HEIC 사진도 됩니다.

**동영상**(.mov/.mp4/.m4v)도 사진과 같이 넣으면 글에 들어갑니다. 회전 보정·축소·얼굴 모자이크를 거쳐 `v01.mp4`로 정리되고(소리 유지), 발행할 때 에디터의 '동영상' 버튼으로 올라갑니다. 동영상 아래 제목은 Claude가 붙입니다. ffmpeg는 `imageio-ffmpeg` 패키지에 들어 있어 따로 설치할 필요가 없습니다.

**휴대폰에만 있는 사진**이면 "사진은 폰에 있어"라고 말하세요. 맥 화면에 QR 코드가 뜨고, 휴대폰 카메라로 찍으면 업로드 페이지가 열립니다(맥과 같은 Wi‑Fi 필요). 사진 앱에서 사진·동영상을 고른 뒤 '맥으로 보내기'를 누르면 고른 순서대로 글에 들어갑니다. 20분 안에 보내지 않으면 업로드 페이지는 닫힙니다.

**밖에서 휴대폰으로 쓰기:** 맥의 Claude Code에서 `/remote-control` 을 켜 두면 휴대폰 Claude 앱으로 지시할 수 있습니다(맥은 켜져 있고 잠자기 상태가 아니어야 함). 사진은 아이폰 사진 앱에서 공유 → '파일에 저장' → iCloud Drive > **블로그 사진** 폴더에 넣고 "iCloud에 올렸어"라고 말하세요. 발행 직전 화면은 Claude가 캡처(`confirm.png`)로 확인해 알려줍니다.

## 수동으로 쓰기

후기를 직접 쓰고 싶다면:

```bash
.venv/bin/python blogger.py prepare --place "성수동 OO갈비" --photos ./photos --memo "..."
# 출력된 output/<시각>/review.json 의 title, blocks, tags 를 직접 채움
.venv/bin/python blogger.py preview output/<시각>
.venv/bin/python blogger.py publish output/<시각> --confirm
```

- `--confirm`: 에디터에 다 입력한 뒤 발행 버튼 누르기 전에 멈춥니다.
- 자동 입력이 중간에 막히면 브라우저를 열어둔 채 기다리니, 남은 부분을 직접 마무리하면 됩니다.

## 블로그 이벤트 응모 (반자동)

`python events.py` 가 네이버 블로그 공식 블로그의 '블로그 이벤트'에서 새 글을 가져옵니다. Claude가 응모 방법을 정리해 알려주고, **승인한 것만** 응모합니다.

```bash
python blogger.py comment https://blog.naver.com/blogpeople/<글번호> --text "답: OOO\n블로그: https://..." --confirm   # 퀴즈 댓글
python blogger.py categories                                   # 카테고리 번호 확인
python blogger.py prepare --category 39 --photos ./photos --memo "..."   # 맛집이 아닌 일반 글 (--place 생략)
python blogger.py add-tags <내 글번호> --tags 태그1 태그2          # 이미 발행한 글에 태그 추가
```

`--confirm` 을 붙이면 등록 직전에 멈추고 화면을 `output/comment_confirm.png` 로 저장합니다. `output/.go` 를 만들면 등록, `output/.cancel` 이면 취소.

## 주의

- `.naver_profile/` 에 로그인 쿠키가 저장됩니다. 공유하거나 업로드하지 마세요.
- 네이버가 에디터 화면을 바꾸면 [naver.py](naver.py) 위쪽의 셀렉터(`SEL_...`)를 고쳐야 합니다.
- 자동 발행은 네이버 이용약관상 제재 대상이 될 수 있으니 짧은 간격으로 대량 발행하지 마세요.
