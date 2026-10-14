"""원클릭 자동 보정: 히스토그램 분석과 얼굴 밝기로 노출, 화이트밸런스, 톤을 계산.

인물 사진은 얼굴 노출을 우선한다. 결과는 보정값 dict (프리셋과 같은 항목 이름).
brightness(밝기 선호, −100~+100)는 노출을 더하는 대신 목표 밝기와 섀도·하이라이트·흰색·검정·대비 판단 기준을
함께 옮긴다: 밝게 = 목표↑, 그늘을 더 들어 올리고 하이라이트는 더 지킴 / 어둡게 = 목표↓, 그늘과 검정을 깊게.
"""
from __future__ import annotations

import math

import numpy as np

from pipeline import color, tone

FACE_TARGET = 0.62   # 얼굴 볼 영역 목표 밝기 (sRGB 감마)
SCENE_TARGET = 0.42  # 얼굴 없을 때 중간 밝기 목표


def _estimate_wb(lin, meta):
    """밝기 중간대의 무채색에 가까운 픽셀로 광원 색 추정 → 촬영 시 값과 반반 섞음."""
    if meta is None:
        return None
    shot_xy = meta.shot_xy
    shot_t, shot_tint = color.xy_to_temp_tint(*shot_xy)
    small = color.resize_long(lin, 512).reshape(-1, 3)
    lum = small @ color.LUMA
    hi = np.percentile(lum, 99)
    sel = (lum > hi * 0.08) & (lum < hi * 0.95)
    px = small[sel]
    if len(px) < 500:
        return round(shot_t), round(shot_tint)
    chroma = (px.max(1) - px.min(1)) / np.maximum(px.max(1), 1e-6)
    cand = px[chroma < np.percentile(chroma, 15)]
    avg = cand.mean(0)
    xyz = color.SRGB_TO_XYZ @ avg
    xyz = color._cat(color.D65_XY, shot_xy) @ xyz  # 촬영 시 렌더링을 되돌려 장면 기준으로
    x, y = xyz[0] / xyz.sum(), xyz[1] / xyz.sum()
    est_t, est_tint = color.xy_to_temp_tint(x, y)
    # 미레드 공간에서 섞고, 크게 벗어나면 추정치를 믿지 않음
    m_shot, m_est = 1e6 / shot_t, 1e6 / est_t
    if abs(m_est - m_shot) > 120:
        return round(shot_t), round(shot_tint)
    t = 1e6 / (0.5 * m_shot + 0.5 * m_est)
    tint = 0.5 * shot_tint + 0.5 * float(np.clip(est_tint, -40, 40))
    return round(t / 50) * 50, round(tint)


def compute(lin: np.ndarray, meta, faces: list[dict], g_for_faces: np.ndarray | None = None,
            brightness: float = 0) -> dict:
    """lin: 선형 RGB (촬영 시 WB). 반환: {'params': {...}, 'reasons': [...]}"""
    from ai import face as face_mod
    s = float(np.clip(brightness or 0, -100, 100)) / 100
    reasons = []
    params = {}
    wb = _estimate_wb(lin, meta)
    if wb:
        params["temperature"], params["tint"] = wb
        reasons.append(f"화이트밸런스 {wb[0]}K / 틴트 {wb[1]:+d}")
        lin = tone.white_balance(lin, params, meta)

    small = color.resize_long(lin, 1024)
    raw = getattr(meta, "is_raw", True)
    g = tone.to_display(small, raw)
    lum = color.luminance(g)
    face_l = [v for v in face_mod.face_luminance(g, faces) if not math.isnan(v)] if faces else []
    if s:
        reasons.append(f"밝기 선호 {s * 100:+.0f}")
    if face_l:
        cur, target = float(np.median(face_l)), FACE_TARGET + 0.08 * s
        reasons.append(f"얼굴 밝기 {cur:.2f} → 목표 {target:.2f}")
    else:
        cur, target = float(np.percentile(lum, 50)) * 0.5 + float(lum.mean()) * 0.5, SCENE_TARGET + 0.10 * s
        reasons.append(f"장면 중간 밝기 {cur:.2f} → 목표 {target:.2f}")
    ev = math.log2(max(color.srgb_decode(np.float32(target)), 1e-4) / max(color.srgb_decode(np.float32(cur)), 1e-4))
    # 하이라이트가 너무 많이 날아가지 않게 제한 (밝게일 때는 아래에서 하이라이트를 더 지키므로 조금 더 허용)
    p995 = float(np.percentile(color.luminance(small), 99.5))
    if p995 > 0:
        ev = min(ev, math.log2((1.6 + 0.8 * max(s, 0)) / p995)) if not face_l else ev
    ev = float(np.clip(ev, -2.0, 3.0))
    params["exposure"] = round(ev, 2)

    after = color.luminance(tone.to_display(tone.exposure(small, ev), raw))
    clipped = float((after > 0.97).mean())
    dark = float(np.percentile(after, 10))
    if clipped > 0.005:
        params["highlights"] = -int(min(70 + 15 * max(s, 0), 20 + clipped * 1500))
        reasons.append(f"하이라이트 클리핑 {clipped * 100:.1f}% → 하이라이트 {params['highlights']}")
    shadow_floor = 0.12 + 0.08 * s  # 이보다 어두운 그늘은 들어 올린다
    if dark < shadow_floor:
        params["shadows"] = int(min(50 + 20 * max(s, 0), (shadow_floor - dark) * 400 + 10))
        reasons.append(f"어두운 영역(하위 10% {dark:.2f}) → 섀도 +{params['shadows']}")
    if s > 0:  # 밝게: 그늘도 함께 밝혀 화사하게
        params["shadows"] = max(params.get("shadows", 0), round(20 * s))
    elif s < 0 and "shadows" not in params:  # 어둡게: 그늘을 조금 가라앉힌다
        params["shadows"] = round(15 * s)
    p_hi = float(np.percentile(after, 99.5))
    white_floor = 0.88 + 0.04 * s
    if p_hi < white_floor:
        params["whites"] = int(min(40, (white_floor + 0.04 - p_hi) * 150))
    p_lo = float(np.percentile(after, 0.5))
    blacks = -min(30, p_lo * 200) if p_lo > 0.06 else 0
    blacks = blacks * (1 - 0.5 * max(s, 0)) + 20 * min(s, 0)  # 밝게: 검정을 덜 누름 / 어둡게: 더 깊게
    if round(blacks):
        params["blacks"] = int(round(blacks))
    if abs(s) >= 0.2:  # 밝게는 대비를 살짝 풀고, 어둡게는 살짝 올려 깊이를 준다
        params["contrast"] = round(-10 * s)
    return {"params": params, "reasons": reasons}
