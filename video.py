"""동영상 정리: 회전 보정 + 축소 + 얼굴 모자이크 후 H.264 mp4로 다시 만든다 (소리는 그대로).

ffmpeg는 imageio-ffmpeg 패키지에 들어 있는 것을 쓴다(따로 설치할 필요 없음).
ffmpeg가 아이폰 동영상의 회전 정보를 적용하고(HEVC도 됨), 프레임마다 faces.py로 얼굴을 찾아 가린다.
"""
import re
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

import faces

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
MAX_SIDE = 1280
FPS = 30      # 가변 프레임(아이폰)이어도 소리와 어긋나지 않게 고정 프레임으로 다시 만든다
HOLD = 6      # 얼굴을 놓친 프레임에도 직전 N프레임의 모자이크를 유지해 깜빡이며 드러나지 않게 한다
THUMBS = 3    # Claude가 보고 후기를 쓰도록 뽑는 장면 수


def _first_frame(src: Path) -> np.ndarray:
    res = subprocess.run([FFMPEG, "-v", "error", "-i", str(src), "-frames:v", "1",
                          "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True)
    if res.returncode or not res.stdout:
        raise RuntimeError(f"동영상을 읽을 수 없습니다: {src.name}\n{res.stderr.decode(errors='ignore')[-500:]}")
    return cv2.imdecode(np.frombuffer(res.stdout, np.uint8), cv2.IMREAD_COLOR)


def _duration(path: Path) -> float:
    err = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True, errors="ignore").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def prepare(src: Path, dest: Path) -> tuple[int, list[Path]]:
    """src를 dest(.mp4)로 정리한다. (얼굴이 나온 프레임 수, 장면 캡처 jpg 목록)을 돌려준다."""
    h, w = _first_frame(src).shape[:2]
    scale = min(1, MAX_SIDE / max(w, h))
    W, H = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2  # H.264는 짝수 크기만 된다
    dec = subprocess.Popen([FFMPEG, "-v", "error", "-i", str(src), "-map", "0:v:0", "-r", str(FPS),
                            "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([FFMPEG, "-v", "error", "-y",
                            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-i", str(src), "-map", "0:v", "-map", "1:a:0?",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(dest)],
                           stdin=subprocess.PIPE)
    size = W * H * 3
    recent: list[list] = []
    hit = 0
    try:
        while len(buf := dec.stdout.read(size)) == size:
            frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
            boxes = faces.find_faces(frame)
            hit += bool(boxes)
            recent = (recent + [boxes])[-HOLD:]
            for b in {b for bs in recent for b in bs}:
                faces.pixelate(frame, *b)
            enc.stdin.write(frame.tobytes())
    finally:
        enc.stdin.close()
        dec.stdout.close()
        dec.wait()
    if enc.wait() != 0:
        raise RuntimeError(f"동영상 변환 실패: {src.name}")

    # 모자이크된 결과물에서 장면을 뽑는다 (처음·중간·끝 부근)
    dur = _duration(dest)
    thumbs = []
    for k in range(THUMBS):
        t = dur * (k + 0.5) / THUMBS
        out = dest.with_name(f"{dest.stem}-{k + 1}.jpg")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(dest),
                        "-frames:v", "1", "-q:v", "3", str(out)], check=True)
        thumbs.append(out)
    return hit, thumbs
