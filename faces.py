"""사진 속 사람 얼굴을 찾아 모자이크한다 (OpenCV YuNet).

거울 천장에 거꾸로 비친 얼굴도 잡도록 180도 돌린 사진에서도 한 번 더 찾는다.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
SCORE = 0.6   # 낮을수록 더 많이 잡음 (오탐 시 엉뚱한 곳이 모자이크될 수 있음)
PAD = 0.35    # 얼굴 박스를 넓혀 머리카락/귀까지 가림
BLOCKS = 8    # 모자이크 칸 수 (얼굴 폭 기준)
FOOD_RED = 0.2  # 진한 빨강/주황 픽셀 비율이 이보다 크면 음식(김치·연어 등) 오탐으로 보고 건너뜀
                # 실측: 실제 얼굴 0.00~0.06, 음식 오탐 0.27~0.86


_detectors: dict[tuple[int, int], "cv2.FaceDetectorYN"] = {}


def _detect(bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    h, w = bgr.shape[:2]
    det = _detectors.get((w, h))
    if det is None:  # 동영상은 프레임마다 같은 크기라 한 번 만든 검출기를 재사용한다
        det = _detectors[(w, h)] = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), SCORE, 0.3, 5000)
    _, faces = det.detect(bgr)
    return [] if faces is None else [tuple(map(int, f[:4])) for f in faces]


def _is_food(bgr: np.ndarray, x, y, w, h) -> bool:
    """얼굴 박스 안이 김치처럼 진한 빨강/주황이면 음식으로 본다(사람 피부는 채도가 훨씬 낮다)."""
    roi = bgr[max(0, y):y + h, max(0, x):x + w]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 120, 60), (20, 255, 255)) | cv2.inRange(hsv, (160, 120, 60), (180, 255, 255))
    return red.mean() / 255 > FOOD_RED


def pixelate(bgr: np.ndarray, x, y, w, h):
    H, W = bgr.shape[:2]
    px, py = int(w * PAD), int(h * PAD)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(W, x + w + px), min(H, y + h + py)
    roi = bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return
    n = max(2, min(BLOCKS, roi.shape[1] // 2))
    small = cv2.resize(roi, (n, max(2, n * roi.shape[0] // roi.shape[1])), interpolation=cv2.INTER_LINEAR)
    bgr[y0:y1, x0:x1] = cv2.resize(small, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST)


def find_faces(bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """모자이크할 얼굴 박스 목록 (BGR 이미지 기준)."""
    H, W = bgr.shape[:2]
    boxes = _detect(bgr)
    for x, y, w, h in _detect(cv2.rotate(bgr, cv2.ROTATE_180)):
        boxes.append((W - x - w, H - y - h, w, h))  # 원래 좌표로 되돌림
    return [b for b in boxes if not _is_food(bgr, *b)]  # 음식에는 모자이크하지 않는다


def mosaic_faces(img: Image.Image) -> tuple[Image.Image, int]:
    """얼굴을 모자이크한 사진과 찾은 얼굴 수를 돌려준다."""
    bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    boxes = find_faces(bgr)
    for b in boxes:
        pixelate(bgr, *b)
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), len(boxes)
