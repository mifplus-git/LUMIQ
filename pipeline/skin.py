"""피부 보정: 얼굴 인식 마스크(눈·입술 제외) 영역만 밝기, 매끈함, 채도, 따뜻함을 보정."""
from __future__ import annotations

import numpy as np

from . import color


def active(sk) -> bool:
    return bool(sk) and any(sk.get(k) for k in ("brightness", "smooth", "saturation", "warmth"))


def apply(g: np.ndarray, sk: dict, faces: list[dict], log=print) -> np.ndarray:
    if not active(sk):
        return g
    from ai import face
    if not faces:
        log("  피부 보정 건너뜀: 얼굴 없음")
        return g
    mask = face.skin_mask(g, faces)[..., None]
    adj = g.copy()
    h, w = g.shape[:2]
    smooth = sk.get("smooth", 0) / 100.0
    if smooth:
        size = max(max(f["bbox"][2] * w, f["bbox"][3] * h) for f in faces)
        r = max(2, int(size * 0.02))
        lum = color.luminance(g)
        for c in range(3):
            low = color.guided_filter(lum, adj[..., c], r, 4e-4)
            adj[..., c] = low + (adj[..., c] - low) * (1 - 0.85 * smooth)
    b = sk.get("brightness", 0) / 100.0
    if b:
        adj = np.power(np.clip(adj, 1e-5, 1), 2.0 ** (-0.45 * b))
    s = sk.get("saturation", 0) / 100.0
    if s:
        l = color.luminance(adj)[..., None]
        adj = l + (adj - l) * (1 + s)
    wm = sk.get("warmth", 0) / 100.0
    if wm:
        adj = adj + wm * 0.035 * np.array([1.0, 0.25, -0.9], np.float32)
    out = g + (np.clip(adj, 0, 1) - g) * mask
    return np.clip(out, 0, 1).astype(np.float32)
