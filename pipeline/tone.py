"""톤: 화이트밸런스, 노출, 디헤이즈, 하이라이트·섀도·화이트·블랙, 대비, 톤 커브,
텍스처·명료도, 바이브런스·채도, HSL, 컬러 그레이딩.

입력은 선형 RGB, 출력은 sRGB 감마 RGB(0~1, float32).
라이트룸 내부 알고리즘의 근사치다.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import color
from .params import HSL_BANDS

HSL_CENTERS = [0, 30, 60, 120, 180, 240, 270, 300]


# ---------- 선형 단계 ----------

def white_balance(lin, p, meta):
    if meta is None or (p.get("temperature") is None and p.get("tint") is None):
        return lin
    shot_xy = meta.shot_xy
    shot_t, shot_tint = color.xy_to_temp_tint(*shot_xy)
    t = p.get("temperature", shot_t)
    tint = p.get("tint", shot_tint)
    return np.maximum(color.apply_matrix(lin, color.wb_matrix(shot_xy, t, tint)), 0)


def exposure(lin, ev):
    return lin * np.float32(2.0 ** ev) if ev else lin


def _soft_clip(lin):
    """1.0 위 하이라이트를 부드럽게 눌러 넣는다 (노출을 내렸을 때 디테일 복원용)."""
    knee = 0.9
    over = lin > knee
    if not over.any():
        return lin
    out = lin.copy()
    x = (lin[over] - knee) / (1 - knee)
    out[over] = knee + (1 - knee) * x / (1 + x)
    return out


def base_curve(g):
    """기본 렌더링 커브 (카메라 JPEG처럼 약간의 S자)."""
    return np.clip(g - 0.06 * np.sin(2 * np.pi * g) / (2 * np.pi) * 2.5, 0, 1).astype(np.float32)


# ---------- 감마 단계 ----------

def _ratio_apply(rgb, lum, new_lum):
    ratio = np.clip(new_lum / np.maximum(lum, 1e-4), 0, 8)
    return rgb * ratio[..., None]


def dehaze(g, amount):
    if not amount:
        return g
    a = amount / 100.0
    small = color.resize_long(g, 512)
    dark = cv2.erode(small.min(axis=2), np.ones((15, 15), np.uint8))
    flat = dark.ravel()
    idx = np.argsort(flat)[-max(1, flat.size // 1000):]
    A = small.reshape(-1, 3)[idx].mean(axis=0).clip(0.5, 1.0).astype(np.float32)
    if a > 0:
        t = 1 - 0.9 * a * dark / A.max()
        gs = color.luminance(small)
        t = color.guided_filter(gs, t.astype(np.float32), 20, 1e-3)
        t = cv2.resize(t, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_LINEAR)
        t = np.clip(t, 0.25, 1)[..., None]
        return np.clip((g - A) / t + A, 0, 1).astype(np.float32)
    k = -a * 0.45
    return (g * (1 - k) + A * k).astype(np.float32)


def whites_blacks(g, whites, blacks):
    if whites:
        w = whites / 100.0
        g = g + w * 0.25 * np.power(np.clip(g, 0, 1), 3) * (1.2 - g)
    if blacks:
        b = blacks / 100.0
        g = g + b * 0.2 * np.power(np.clip(1 - g, 0, 1), 4)
    return np.clip(g, 0, 1).astype(np.float32)


def shadows_highlights(g, shadows, highlights):
    if not shadows and not highlights:
        return g
    lum = color.luminance(g)
    base = color.smooth_base(lum, 0.03, eps=0.02)
    new = lum.copy()
    if shadows:
        w = np.clip(1 - base / 0.55, 0, 1) ** 1.5
        new = np.power(np.clip(new, 1e-5, 1), 2.0 ** (-(shadows / 100.0) * 1.1 * w))
    if highlights:
        w = np.clip((base - 0.4) / 0.6, 0, 1) ** 1.2
        inv = np.power(np.clip(1 - new, 1e-5, 1), 2.0 ** ((highlights / 100.0) * 1.0 * w))
        new = 1 - inv
    return np.clip(_ratio_apply(g, lum, new), 0, 1).astype(np.float32)


def contrast(g, c):
    if not c:
        return g
    k = 0.75 * c / 100.0
    return np.clip(g - k * np.sin(2 * np.pi * g) / (2 * np.pi), 0, 1).astype(np.float32)


def _curve_lut(points, n=4096):
    pts = sorted((float(x) / 255.0, float(y) / 255.0) for x, y in points)
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    if len(xs) < 2:
        return None
    # 단조 3차 보간 (Fritsch–Carlson)
    h = np.diff(xs)
    d = np.diff(ys) / np.maximum(h, 1e-9)
    m = np.zeros_like(xs)
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1):
        m[i] = 0 if d[i - 1] * d[i] <= 0 else 2 / (1 / d[i - 1] + 1 / d[i])
    t = np.linspace(0, 1, n)
    i = np.clip(np.searchsorted(xs, t) - 1, 0, len(xs) - 2)
    hh = h[i]
    s = np.clip((t - xs[i]) / np.maximum(hh, 1e-9), 0, 1)
    h00 = 2 * s**3 - 3 * s**2 + 1
    h10 = s**3 - 2 * s**2 + s
    h01 = -2 * s**3 + 3 * s**2
    h11 = s**3 - s**2
    out = h00 * ys[i] + h10 * hh * m[i] + h01 * ys[i + 1] + h11 * hh * m[i + 1]
    out = np.where(t < xs[0], ys[0], np.where(t > xs[-1], ys[-1], out))
    return np.clip(out, 0, 1).astype(np.float32)


def _apply_lut1d(x, lut):
    idx = np.clip(x * (len(lut) - 1), 0, len(lut) - 1)
    return np.interp(idx, np.arange(len(lut)), lut).astype(np.float32)


def tone_curves(g, p):
    pc = p.get("tone_curve")
    if pc:
        lut = _curve_lut(pc)
        if lut is not None:
            g = _apply_lut1d(g, lut)
    for i, ch in enumerate(("red", "green", "blue")):
        pts = p.get(f"tone_curve_{ch}")
        if pts:
            lut = _curve_lut(pts)
            if lut is not None:
                g[..., i] = _apply_lut1d(g[..., i], lut)
    return g


def texture_clarity(g, texture, clarity):
    if not texture and not clarity:
        return g
    lum = color.luminance(g)
    new = lum.copy()
    long_edge = max(g.shape[:2])
    if texture:
        sigma = max(0.6, 0.0012 * long_edge)
        band = lum - cv2.GaussianBlur(lum, (0, 0), sigma)
        new = new + (texture / 100.0) * 0.9 * band
    if clarity:
        base = color.smooth_base(lum, 0.02, eps=0.01)
        mid = 4 * lum * (1 - lum)
        new = new + (clarity / 100.0) * 0.7 * (lum - base) * mid
    return np.clip(_ratio_apply(g, lum, np.clip(new, 0, 1)), 0, 1).astype(np.float32)


def _hue_dir(hue_deg):
    """색조(°)의 채도 방향 벡터 (휘도 0)."""
    hsv = np.array([[[hue_deg % 360, 1.0, 1.0]]], dtype=np.float32)
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)[0, 0]
    return rgb - float(rgb @ color.LUMA)


def vibrance_saturation(g, vibrance, saturation):
    if not vibrance and not saturation:
        return g
    lum = color.luminance(g)[..., None]
    chroma = g - lum
    k = np.full(lum.shape, 1 + saturation / 100.0, dtype=np.float32)
    if vibrance:
        mx, mn = g.max(axis=2, keepdims=True), g.min(axis=2, keepdims=True)
        sat = (mx - mn) / np.maximum(mx, 1e-4)
        hue = cv2.cvtColor(g, cv2.COLOR_RGB2HSV)[..., :1]
        skin = np.exp(-((hue - 25) / 18) ** 2)  # 피부 색조 보호
        k = k * (1 + (vibrance / 100.0) * (1 - sat) ** 1.5 * (1 - 0.6 * skin))
    return np.clip(lum + chroma * k, 0, 1).astype(np.float32)


def _band_weights(hue):
    """8개 HSL 대역 가중치 (합이 1인 삼각형 보간)."""
    centers = HSL_CENTERS + [360]
    w = np.zeros(hue.shape + (8,), dtype=np.float32)
    for i in range(8):
        c0, c1 = centers[i], centers[i + 1]
        inside = (hue >= c0) & (hue < c1)
        t = (hue - c0) / (c1 - c0)
        w[..., i] += np.where(inside, 1 - t, 0)
        w[..., (i + 1) % 8] += np.where(inside, t, 0)
    return w


def hsl(g, adj):
    if not adj or not any(adj.get(b) for b in HSL_BANDS):
        return g
    hsv = cv2.cvtColor(g, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    w = _band_weights(h)
    vec = lambda key: np.array([(adj.get(b) or {}).get(key, 0) for b in HSL_BANDS], dtype=np.float32) / 100.0
    dh, ds, dl = w @ vec("hue"), w @ vec("saturation"), w @ vec("luminance")
    cw = np.clip(s * 3, 0, 1)  # 무채색은 영향 적게
    h = (h + dh * 30.0 * cw) % 360
    s = np.clip(s * (1 + ds), 0, 1)
    v = np.clip(v * (1 + 0.5 * dl * cw), 0, 1)
    return cv2.cvtColor(np.dstack([h, s, v]).astype(np.float32), cv2.COLOR_HSV2RGB)


def color_grading(g, cg):
    if not cg:
        return g
    zones = {k: cg.get(k) for k in ("shadows", "midtones", "highlights", "global")}
    if not any(z and (z.get("saturation") or z.get("luminance")) for z in zones.values()):
        return g
    lum = color.luminance(g)[..., None]
    bal = cg.get("balance", 0) / 100.0
    blend = cg.get("blending", 50) / 100.0
    pivot = np.clip(0.5 - 0.25 * bal, 0.15, 0.85)
    soft = 0.6 + 0.8 * blend
    ws = np.clip(1 - lum / (pivot * 1.6), 0, 1) ** (2.0 / soft)
    wh = np.clip((lum - pivot * 0.6) / (1 - pivot * 0.6), 0, 1) ** (2.0 / soft)
    wm = np.clip(1 - ws - wh, 0, 1)
    weights = {"shadows": ws, "midtones": wm, "highlights": wh, "global": np.ones_like(lum)}
    out = g.copy()
    for name, z in zones.items():
        if not z:
            continue
        sat = z.get("saturation", 0) / 100.0
        lumv = z.get("luminance", 0) / 100.0
        if sat:
            out = out + weights[name] * sat * 0.35 * _hue_dir(z.get("hue", 0))
        if lumv:
            out = out + weights[name] * lumv * 0.25
    return np.clip(out, 0, 1).astype(np.float32)


def to_display(lin, raw: bool = True):
    """선형 → sRGB 감마. RAW는 기본 커브를 더하고, JPG 등은 이미 톤이 입혀져 있어 그대로 둔다."""
    g = color.srgb_encode(_soft_clip(lin))
    return base_curve(g) if raw else g


def apply_linear(lin, p, meta):
    lin = white_balance(lin, p, meta)
    lin = exposure(lin, p.get("exposure", 0))
    return lin


def apply_display(g, p):
    g = dehaze(g, p.get("dehaze", 0))
    g = whites_blacks(g, p.get("whites", 0), p.get("blacks", 0))
    g = shadows_highlights(g, p.get("shadows", 0), p.get("highlights", 0))
    g = contrast(g, p.get("contrast", 0))
    g = tone_curves(g, p)
    g = texture_clarity(g, p.get("texture", 0), p.get("clarity", 0))
    g = vibrance_saturation(g, p.get("vibrance", 0), p.get("saturation", 0))
    g = hsl(g, p.get("hsl"))
    g = color_grading(g, p.get("color_grading"))
    return g
