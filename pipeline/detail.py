"""디테일: 노이즈 감소, 샤프닝, 비네팅, 그레인. 입력은 sRGB 감마.

scale은 처리 해상도 / 원본 해상도 (미리보기에서 반경을 맞추기 위함).
"""
from __future__ import annotations

import cv2
import numpy as np

from . import color


def noise_reduction(g, nr, scale=1.0):
    if not nr or not (nr.get("luminance") or nr.get("color")):
        return g
    from ai.denoise import classic
    return classic(g, nr.get("luminance", 0), nr.get("color", 0), scale)


def sharpen(g, sh, scale=1.0):
    if not sh or not sh.get("amount"):
        return g
    amount = sh["amount"] / 100.0
    radius = max(0.3, sh.get("radius", 1.0) * scale)
    detail = sh.get("detail", 25) / 100.0
    masking = sh.get("masking", 0) / 100.0
    lum = color.luminance(g)
    hp = lum - cv2.GaussianBlur(lum, (0, 0), radius)
    lim = 0.015 + 0.2 * detail  # 디테일이 낮으면 큰 윤곽(헤일로)을 억제
    hp = lim * np.tanh(hp / lim)
    if masking > 0:
        sm = cv2.GaussianBlur(lum, (0, 0), max(1.0, 2 * scale))
        gx, gy = cv2.Sobel(sm, cv2.CV_32F, 1, 0), cv2.Sobel(sm, cv2.CV_32F, 0, 1)
        mag = np.sqrt(gx * gx + gy * gy)
        mag /= max(float(np.percentile(mag, 99)), 1e-6)
        th = masking * 0.6
        hp = hp * np.clip((mag - th) / max(0.15, 1 - th) * 2, 0, 1)
    return np.clip(g + (amount * 1.2 * hp)[..., None], 0, 1).astype(np.float32)


def output_sharpen(g, amount=0.35):
    lum = color.luminance(g)
    hp = lum - cv2.GaussianBlur(lum, (0, 0), 0.7)
    return np.clip(g + (amount * hp)[..., None], 0, 1).astype(np.float32)


def vignette(g, vg):
    if not vg or not vg.get("amount"):
        return g
    amount = vg["amount"] / 100.0
    mid = vg.get("midpoint", 50) / 100.0
    feather = vg.get("feather", 50) / 100.0
    h, w = g.shape[:2]
    y, x = np.ogrid[:h, :w]
    nx, ny = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
    r = np.sqrt(nx * nx + ny * ny) / np.sqrt(2)
    start = 0.15 + 0.6 * mid
    width = 0.1 + 0.6 * feather
    t = np.clip((r - start * 0.75) / width, 0, 1)
    wgt = (t * t * (3 - 2 * t)).astype(np.float32)[..., None]
    if amount < 0:
        return np.clip(g * (1 + amount * 0.8 * wgt), 0, 1).astype(np.float32)
    return np.clip(g + (1 - g) * amount * 0.8 * wgt, 0, 1).astype(np.float32)


def grain(g, gr, seed=0):
    """그레인 크기는 이미지 긴 변 기준이라 출력 크기가 달라도 비슷하게 보인다."""
    if not gr or not gr.get("amount"):
        return g
    amount = gr["amount"] / 100.0
    size = gr.get("size", 25) / 100.0
    rough = gr.get("roughness", 50) / 100.0
    h, w = g.shape[:2]
    rng = np.random.default_rng(seed)
    cell = max(1.0, (0.4 + 2.5 * size) * max(h, w) / 2048)
    sh, sw = max(2, int(h / cell)), max(2, int(w / cell))
    noise = rng.standard_normal((sh, sw)).astype(np.float32)
    if rough < 1:
        noise = cv2.GaussianBlur(noise, (0, 0), 0.3 + (1 - rough) * 0.8)
        noise /= max(float(noise.std()), 1e-6)
    noise = cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)
    lum = color.luminance(g)
    mid = (0.3 + 0.7 * 4 * lum * (1 - lum))[..., None]
    return np.clip(g + noise[..., None] * amount * 0.06 * mid, 0, 1).astype(np.float32)
