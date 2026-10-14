"""회전·크롭·자동 수평.

rotate 각도는 라이트룸처럼 +가 시계 방향.
회전 후에는 빈 모서리가 생기지 않는 범위에서 지정 비율의 가장 큰 영역을 자른다.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import color

MAX_AUTO_ANGLE = 5.0  # 자동 수평이 고칠 최대 각도(°)
MIN_LINE_SUPPORT = 0.8  # 일치하는 직선 길이 합 / 긴 변, 이보다 작으면 자동 수평 안 함


def rotate90_flip(img, rotate90=None, flip=None):
    if rotate90 == "cw":
        img = np.rot90(img, -1)
    elif rotate90 == "ccw":
        img = np.rot90(img, 1)
    elif rotate90 in ("180", 180):
        img = img[::-1, ::-1]
    if flip == "h":
        img = img[:, ::-1]
    elif flip == "v":
        img = img[::-1]
    return np.ascontiguousarray(img)


def detect_level(img) -> dict:
    """OpenCV 직선 검출로 기울기 추정. 반환 angle은 보정에 쓸 rotate 값(°)."""
    small = color.resize_long(img, 1024)
    g = color.luminance(small)  # 선형 입력
    g = g / max(float(np.percentile(g, 99)), 1e-4)  # 어두운 사진도 같은 기준으로
    g8 = (color.srgb_encode(g) * 255).astype(np.uint8)
    edges = cv2.Canny(cv2.GaussianBlur(g8, (3, 3), 0), 50, 150)
    long_edge = max(g8.shape)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=80,
                            minLineLength=int(long_edge * 0.08), maxLineGap=6)
    if lines is None:
        return {"angle": 0.0, "confident": False, "lines": 0}
    devs, weights = [], []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):  # OpenCV 버전에 따라 (N,1,4) 또는 (N,4)
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        length = math.hypot(x2 - x1, y2 - y1)
        for ref in (0, 90, 180):
            d = a - ref
            if abs(d) <= MAX_AUTO_ANGLE:
                devs.append(d)
                weights.append(length)
    if not devs:
        return {"angle": 0.0, "confident": False, "lines": 0}
    devs, weights = np.array(devs), np.array(weights)
    order = np.argsort(devs)
    cum = np.cumsum(weights[order])
    median = float(devs[order][np.searchsorted(cum, cum[-1] / 2)])
    near = np.abs(devs - median) < 0.75
    support = float(weights[near].sum() / long_edge)
    angle = float(np.average(devs[near], weights=weights[near]))
    confident = support >= MIN_LINE_SUPPORT and near.sum() >= 3
    return {"angle": round(-angle, 2) if confident else 0.0, "confident": bool(confident),
            "lines": int(near.sum()), "support": round(support, 2), "raw_angle": round(-angle, 2)}


def parse_ratio(crop, w, h, orientation="auto"):
    if not crop or str(crop).lower() in ("none", "original", "원본"):
        return w / h
    a, b = (float(x) for x in str(crop).split(":"))
    r = a / b
    if orientation == "portrait":
        return min(r, 1 / r)
    if orientation == "landscape":
        return max(r, 1 / r)
    if orientation == "as_is":
        return r
    # auto: 사진 방향에 맞춤 (라이트룸과 같음)
    return max(r, 1 / r) if w >= h else min(r, 1 / r)


def _fits(cx, cy, cw, ch, w, h, ang):
    """회전된 원본(w×h, 중심 기준) 안에 크롭 사각형 네 꼭짓점이 모두 들어가는지."""
    c, s = math.cos(ang), math.sin(ang)
    for dx in (-cw / 2, cw / 2):
        for dy in (-ch / 2, ch / 2):
            x, y = cx + dx, cy + dy
            u = x * c + y * s
            v = -x * s + y * c
            if abs(u) > w / 2 + 1e-6 or abs(v) > h / 2 + 1e-6:
                return False
    return True


def largest_rect(w, h, angle, ratio):
    """회전(angle°)된 w×h 사진 안에 들어가는, 비율 ratio(가로/세로)의 가장 큰 중앙 사각형 크기."""
    ang = math.radians(abs(angle))
    c, s = math.cos(ang), math.sin(ang)
    ch = min(h / (ratio * s + c), w / (ratio * c + s), h, w / ratio)
    return ch * ratio, ch


def fit_rect(cx, cy, cw, ch, w, h, angle):
    """크롭 사각형(중심 기준 픽셀)이 회전된 사진 밖으로 나가면, 먼저 안쪽으로 옮기고 그래도 안 되면 줄인다."""
    a = math.radians(angle)
    if _fits(cx, cy, cw, ch, w, h, a):
        return cx, cy, cw, ch
    lo, hi = 0.0, 1.0  # 중심을 사진 중앙 쪽으로
    for _ in range(30):
        m = (lo + hi) / 2
        if _fits(cx * m, cy * m, cw, ch, w, h, a):
            lo = m
        else:
            hi = m
    if _fits(cx * lo, cy * lo, cw, ch, w, h, a) and lo > 0:
        return cx * lo, cy * lo, cw, ch
    lo, hi = 0.0, 1.0  # 크기를 줄임 (비율 유지)
    for _ in range(30):
        m = (lo + hi) / 2
        if _fits(cx, cy, cw * m, ch * m, w, h, a):
            lo = m
        else:
            hi = m
    if lo > 0.05:
        return cx, cy, cw * lo, ch * lo
    mw, mh = largest_rect(w, h, angle, cw / ch)
    return 0.0, 0.0, mw, mh


def _warp(img, angle, cw, ch, ox, oy):
    """회전과 크롭을 아핀 변환 한 번으로. ox, oy는 사진 중앙에서 크롭 중심까지(회전 후 화면 기준 픽셀)."""
    h, w = img.shape[:2]
    cw_i, ch_i = max(1, int(round(cw))), max(1, int(round(ch)))
    if abs(angle) < 1e-3:
        x0 = int(round(w / 2 + ox - cw_i / 2))
        y0 = int(round(h / 2 + oy - ch_i / 2))
        x0 = min(max(x0, 0), max(w - cw_i, 0))
        y0 = min(max(y0, 0), max(h - ch_i, 0))
        return np.ascontiguousarray(img[y0:y0 + ch_i, x0:x0 + cw_i])
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
    m[0, 2] += cw_i / 2 - w / 2 - ox
    m[1, 2] += ch_i / 2 - h / 2 - oy
    return cv2.warpAffine(img, m, (cw_i, ch_i), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def crop_rotate(img, angle=0.0, crop=None, center=None, orientation="auto"):
    """비율 크롭: 회전 후 빈 모서리가 없는 가장 큰 영역 (center로 위치 이동)."""
    h, w = img.shape[:2]
    cw, ch = largest_rect(w, h, angle, parse_ratio(crop, w, h, orientation))
    ox = oy = 0.0
    if center:
        ox = (float(center[0]) - 0.5) * w
        oy = (float(center[1]) - 0.5) * h
        a_signed = math.radians(angle)
        if not _fits(ox, oy, cw, ch, w, h, a_signed):
            lo, hi = 0.0, 1.0  # 크기를 유지하고 이동량을 줄인다
            for _ in range(30):
                m = (lo + hi) / 2
                if _fits(ox * m, oy * m, cw, ch, w, h, a_signed):
                    lo = m
                else:
                    hi = m
            ox, oy = ox * lo, oy * lo
    return _warp(img, angle, cw, ch, ox, oy)


def rect_to_pixels(rect, w, h):
    """crop_rect [x, y, 가로, 세로] (0~1, 회전 후 화면 기준) → 중심 기준 픽셀 (cx, cy, cw, ch)."""
    x, y, rw, rh = (float(v) for v in rect)
    return (x + rw / 2 - 0.5) * w, (y + rh / 2 - 0.5) * h, rw * w, rh * h


def pixels_to_rect(cx, cy, cw, ch, w, h):
    return [round((cx - cw / 2) / w + 0.5, 5), round((cy - ch / 2) / h + 0.5, 5), round(cw / w, 5), round(ch / h, 5)]


def crop_free(img, angle, rect):
    """앱에서 화면으로 지정한 자유 크롭. 사진 밖으로 나가면 안쪽으로 맞춘다."""
    h, w = img.shape[:2]
    cx, cy, cw, ch = fit_rect(*rect_to_pixels(rect, w, h), w, h, angle)
    return _warp(img, angle, cw, ch, cx, cy)


def apply(img, p, level_hint=None):
    """level_hint: 미리 계산한 detect_level 결과(미리보기와 최종 결과를 같게 하기 위함)."""
    img = rotate90_flip(img, p.get("rotate90"), p.get("flip"))
    angle = float(p.get("rotate", 0) or 0)
    if p.get("auto_level", True):
        lv = level_hint if level_hint is not None else detect_level(img)
        angle += lv["angle"]
    if p.get("crop_rect"):
        return crop_free(img, angle, p["crop_rect"]), angle
    if abs(angle) < 1e-3 and not p.get("crop") and not p.get("crop_center"):
        return img, angle
    return crop_rotate(img, angle, p.get("crop"), p.get("crop_center"), p.get("crop_orientation", "auto")), angle
