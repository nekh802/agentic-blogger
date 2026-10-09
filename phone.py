"""휴대폰에서 사진·동영상을 골라 맥으로 보내는 임시 업로드 페이지.

같은 Wi-Fi에서 맥 화면의 QR 코드를 찍으면 업로드 페이지가 열리고,
사진을 보내면 서버는 자동으로 종료된다. URL에 무작위 토큰이 있어 주소를 모르는 기기는 접근할 수 없다.
"""
import secrets
import socket
import subprocess
import threading
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import qrcode

TIMEOUT = 1200  # 20분 안에 안 보내면 종료 (동영상은 전송이 오래 걸린다)

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>사진 보내기</title>
<style>
body{font-family:-apple-system,sans-serif;margin:0;padding:24px 16px;background:#f5f6f7;color:#222}
h1{font-size:22px;margin:0 0 8px}p{color:#666;margin:0 0 20px;line-height:1.5}
label.pick{display:block;padding:18px;border:2px dashed #03c75a;border-radius:12px;text-align:center;
 color:#03c75a;font-weight:600;background:#fff}
input[type=file]{display:none}
#grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:16px 0}
#grid img,#grid video{width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px}
button{width:100%;padding:16px;border:0;border-radius:12px;background:#03c75a;color:#fff;
 font-size:17px;font-weight:600}button:disabled{background:#aaa}
</style></head><body>
<h1>📷 블로그 사진 보내기</h1>
<p>글에 넣을 사진·동영상을 고르세요. 고른 순서대로 글에 들어갑니다.</p>
<form id="f" method="post" enctype="multipart/form-data">
<label class="pick">사진·동영상 선택<input id="i" type="file" name="photos" accept="image/*,video/*" multiple></label>
<div id="grid"></div>
<button id="b" disabled>맥으로 보내기</button>
</form>
<script>
const i=document.getElementById('i'),g=document.getElementById('grid'),b=document.getElementById('b');
i.onchange=()=>{g.innerHTML='';for(const f of i.files){const v=f.type.startsWith('video/'),
 im=document.createElement(v?'video':'img');im.src=URL.createObjectURL(f)+(v?'#t=0.1':'');im.muted=true;im.playsInline=true;
 g.appendChild(im)}b.disabled=!i.files.length;b.textContent=`${i.files.length}개 맥으로 보내기`};
document.getElementById('f').onsubmit=()=>{b.disabled=true;b.textContent='보내는 중... 화면을 끄지 마세요'};
</script></body></html>"""

DONE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 16px">
<h1>✅ {n}개 전송 완료</h1><p>맥으로 돌아가세요. 이 창은 닫아도 됩니다.</p></body></html>"""


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # 실제로 패킷을 보내지 않고 기본 경로의 IP만 얻는다
        return s.getsockname()[0]
    finally:
        s.close()


def receive(dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(8)
    saved: list[Path] = []

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body=""):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(200, PAGE) if self.path == f"/{token}" else self._send(404)

        def do_POST(self):
            if self.path != f"/{token}":
                return self._send(404)
            body = self.rfile.read(int(self.headers["Content-Length"]))
            msg = BytesParser(policy=email_policy).parsebytes(
                f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body)
            for part in msg.iter_parts():
                if not part.get_filename():
                    continue
                ext = Path(part.get_filename()).suffix.lower() or (
                    ".mov" if part.get_content_type().startswith("video/") else ".jpg")
                path = dest / f"{len(saved) + 1:02d}{ext}"  # 아이폰은 파일명이 다 같을 수 있어 순번으로 저장
                path.write_bytes(part.get_payload(decode=True))
                saved.append(path)
            self._send(200, DONE.format(n=len(saved)))
            if saved:
                threading.Thread(target=server.shutdown).start()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    url = f"http://{_lan_ip()}:{server.server_port}/{token}"

    qr_path = dest / "qr.png"
    qrcode.make(url).save(qr_path)
    subprocess.run(["open", str(qr_path)])  # 맥 화면에 QR 띄우기
    print(f"휴대폰 카메라로 맥 화면의 QR을 찍거나 이 주소를 여세요 (같은 Wi-Fi): {url}", flush=True)

    timer = threading.Timer(TIMEOUT, server.shutdown)
    timer.start()
    server.serve_forever()
    timer.cancel()
    server.server_close()
    qr_path.unlink(missing_ok=True)
    return saved
