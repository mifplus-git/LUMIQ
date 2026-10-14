"""얼굴 검출: MediaPipe Face Landmarker (models/face_landmarker.task).

모델이 없거나 실패하면 OpenCV Haar 검출로 대신한다 (이때는 눈·입술 제외 없음).
"""
from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

import cv2
import numpy as np

from pipeline import color

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"
DETECT_SIZE = 1280
_landmarker = None
_lock = threading.Lock()  # 앱의 미리보기 스레드와 export 스레드가 함께 쓰므로


@contextlib.contextmanager
def _quiet_stderr():
    """MediaPipe(C++)가 stderr에 찍는 초기화 로그를 숨긴다."""
    fd = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(fd, 2)
        os.close(fd)
        os.close(devnull)


def _get_landmarker():
    global _landmarker
    if _landmarker is None:
        from mediapipe.tasks.python import BaseOptions, vision
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            num_faces=10,
            min_face_detection_confidence=0.4,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def _connections():
    from mediapipe.tasks.python.vision import FaceLandmarksConnections as C
    idx = lambda conns: sorted({c.start for c in conns} | {c.end for c in conns})
    return {
        "oval": idx(C.FACE_LANDMARKS_FACE_OVAL),
        "exclude": [idx(C.FACE_LANDMARKS_LEFT_EYE), idx(C.FACE_LANDMARKS_RIGHT_EYE),
                    idx(C.FACE_LANDMARKS_LEFT_EYEBROW), idx(C.FACE_LANDMARKS_RIGHT_EYEBROW),
                    idx(C.FACE_LANDMARKS_LIPS)],
    }


def _to_u8(g: np.ndarray) -> np.ndarray:
    small = color.resize_long(g, DETECT_SIZE)
    return np.ascontiguousarray((np.clip(small, 0, 1) * 255).astype(np.uint8))


def detect(g: np.ndarray) -> list[dict]:
    """g: sRGB 감마 RGB(0~1). 반환 좌표는 0~1 정규화.
    각 얼굴: bbox [x, y, w, h], oval/exclude 다각형(정규화 좌표), method."""
    u8 = _to_u8(g)
    if MODEL_PATH.exists():
        try:
            import mediapipe as mp
            with _lock, _quiet_stderr():
                res = _get_landmarker().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=u8))
            conn = _connections()
            faces = []
            for lms in res.face_landmarks:
                pts = np.array([[p.x, p.y] for p in lms], np.float32)
                oval = pts[conn["oval"]]
                x0, y0 = oval.min(0)
                x1, y1 = oval.max(0)
                faces.append({
                    "bbox": [float(x0), float(y0), float(x1 - x0), float(y1 - y0)],
                    "oval": oval,
                    "exclude": [pts[e] for e in conn["exclude"]],
                    "method": "mediapipe",
                })
            return faces
        except Exception as e:
            print(f"  MediaPipe 얼굴 검출 실패({e}), OpenCV로 대체")
    gray = cv2.cvtColor(u8, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    h, w = gray.shape
    rects = cascade.detectMultiScale(gray, 1.1, 5, minSize=(max(24, w // 40), max(24, w // 40)))
    faces = []
    for x, y, fw, fh in rects:
        cx, cy = (x + fw / 2) / w, (y + fh / 2) / h
        t = np.linspace(0, 2 * np.pi, 40)
        oval = np.stack([cx + 0.45 * fw / w * np.cos(t), cy + 0.6 * fh / h * np.sin(t)], 1).astype(np.float32)
        faces.append({"bbox": [x / w, y / h, fw / w, fh / h], "oval": oval, "exclude": [], "method": "opencv"})
    return faces


def _poly(mask, pts, shape, val):
    h, w = shape
    p = np.round(pts * [w, h]).astype(np.int32)
    cv2.fillConvexPoly(mask, cv2.convexHull(p), val)


def skin_mask(g: np.ndarray, faces: list[dict]) -> np.ndarray:
    """눈·눈썹·입술을 뺀 얼굴 피부 마스크 (0~1, 가장자리 부드럽게)."""
    h, w = g.shape[:2]
    mask = np.zeros((h, w), np.float32)
    for f in faces:
        fm = np.zeros((h, w), np.float32)
        _poly(fm, f["oval"], (h, w), 1.0)
        size = max(f["bbox"][2] * w, f["bbox"][3] * h)
        for ex in f["exclude"]:
            em = np.zeros((h, w), np.uint8)
            _poly(em, ex, (h, w), 1)
            k = max(3, int(size * 0.03)) | 1
            em = cv2.dilate(em, np.ones((k, k), np.uint8))
            fm[em > 0] = 0
        fm *= _skin_likelihood(g, fm, size)
        sigma = max(1.0, size * 0.02)
        fm = cv2.GaussianBlur(fm, (0, 0), sigma)
        mask = np.maximum(mask, fm)
    return mask


def _skin_likelihood(g: np.ndarray, region: np.ndarray, size: float) -> np.ndarray:
    """얼굴 안쪽 픽셀에서 피부색(Cr, Cb) 분포를 구해, 머리카락·모자·배경을 걸러낸다.
    고정 범위 대신 그 얼굴의 색을 기준으로 하므로 조명·화이트밸런스가 달라도 맞는다."""
    ys, xs = np.nonzero(region > 0.5)
    if len(ys) < 50:
        return np.ones_like(region)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    ycc = cv2.cvtColor(g[y0:y1, x0:x1].astype(np.float32), cv2.COLOR_RGB2YCrCb)
    crcb = ycc[..., 1:].reshape(-1, 2)
    sel = (region[y0:y1, x0:x1] > 0.5).ravel()
    samples = crcb[sel]
    med = np.median(samples, axis=0)
    dist = np.linalg.norm(samples - med, axis=1)
    core = samples[dist <= np.percentile(dist, 70)]  # 바깥 30%(머리카락 등) 빼고 통계
    cov = np.cov(core.T) + np.eye(2) * 1e-5
    inv = np.linalg.inv(cov)
    d = crcb - core.mean(0)
    md = np.sqrt(np.einsum("ij,jk,ik->i", d, inv, d)).reshape(y1 - y0, x1 - x0)
    like = np.clip(3.5 - md, 0, 1).astype(np.float32)  # 3σ 안쪽은 피부
    like = cv2.GaussianBlur(like, (0, 0), max(1.0, size * 0.01))
    out = np.zeros_like(region)
    out[y0:y1, x0:x1] = like
    return out


def face_luminance(g: np.ndarray, faces: list[dict]) -> list[float]:
    out = []
    h, w = g.shape[:2]
    lum = color.luminance(g)
    for f in faces:
        x, y, fw, fh = f["bbox"]
        # 얼굴 가운데 영역(볼·코)만
        x0, x1 = int((x + fw * 0.25) * w), int((x + fw * 0.75) * w)
        y0, y1 = int((y + fh * 0.35) * h), int((y + fh * 0.75) * h)
        region = lum[max(y0, 0):max(y1, y0 + 1), max(x0, 0):max(x1, x0 + 1)]
        out.append(float(np.median(region)) if region.size else float("nan"))
    return out
