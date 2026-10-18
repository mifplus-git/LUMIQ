"""사진 한 장 처리: 디코딩 → 렌즈 → 회전·크롭 → AI 노이즈 제거 → 톤 → 피부 → LUT → 디테일 → export.

단계별 함수로 나눠 두어 앱은 앞 단계(디코딩·기하·노이즈 제거)를 캐시하고
슬라이더를 움직일 때 뒤 단계(render)만 다시 계산한다.
"""
from __future__ import annotations

import math
import time
import zlib
from pathlib import Path

import cv2
import numpy as np

from . import color, decode, detail, export, geometry, lens, lut, params as P, skin, tone

PREVIEW_EDGE = 1024
# 자동 보정이 켜져 있을 때 프리셋 값을 자동값에 더하는 항목 (나머지는 프리셋이 덮어씀)
ADDITIVE_KEYS = ("exposure", "highlights", "shadows", "whites", "blacks")
SUMMARY_KEYS = ("temperature", "tint", "exposure", "contrast", "highlights", "shadows", "whites", "blacks")
GEOMETRY_KEYS = ("rotate90", "flip", "rotate", "auto_level", "crop", "crop_center", "crop_orientation", "crop_rect")


def combine_auto(auto_p: dict, base: dict, upper: dict) -> dict:
    """자동값 위에 프리셋을 얹고(노출·톤은 더하기), 그 위를 사진별 yaml·edit.json·CLI가 덮어쓴다."""
    layered = P.deep_merge(auto_p, base)
    for k in ADDITIVE_KEYS:
        if k in auto_p and k in base:
            lo, hi = P.RANGES[k]
            layered[k] = round(min(max(auto_p[k] + base[k], lo), hi), 2)
    return P.deep_merge(layered, upper)


def load_sidecar(path: Path) -> dict:
    for ext in (".yaml", ".yml"):
        sc = path.with_suffix(ext)
        if sc.exists():
            return P.load_file(sc) or {}
    return {}


def settings_for(path: Path, layers: dict, log=print) -> tuple[dict, dict]:
    """우선순위(뒤가 앞을 덮어씀): 프리셋/xmp < 사진별 yaml < edit.json < CLI.
    자동 보정은 이미지를 본 뒤 맨 아래에 깔리므로 여기서는 플래그만 정한다.
    반환: (병합된 값, 출처 정보)"""
    sidecar = load_sidecar(path)
    edit = layers.get("params_for")(path) if layers.get("params_for") else {}
    cli = layers.get("cli", {})
    upper = P.deep_merge(P.deep_merge(sidecar, edit), cli)
    preset_name = upper.get("preset")
    xmp_path = upper.get("xmp")
    base = {}
    if preset_name:
        try:
            base = P.load_preset(preset_name)
        except SystemExit as e:  # 지운 프리셋을 쓰던 사진: 프리셋 없이 처리
            log(f"  [경고] {e} — 프리셋 없이 처리합니다")
    if xmp_path:
        from presets.xmp_reader import read_xmp
        xp = read_xmp(Path(xmp_path).expanduser())
        for u in xp.pop("_unsupported", []):
            log(f"  [xmp] 지원하지 않는 항목 무시: {u}")
        xp.pop("_name", None)
        base = P.deep_merge(base, xp)
    merged = P.deep_merge(base, upper)
    if "camera_match" not in merged and decode.is_raw(path):  # 사진에 정하지 않았으면 설정의 기본값
        merged["camera_match"] = bool(P.app_config().get("camera_match_default", False))
    src = {"preset": preset_name, "xmp": xmp_path, "sidecar": bool(sidecar), "edit": bool(edit),
           "layers": (base, upper)}
    return merged, src


# ---------- 단계 ----------

def stage_decode(path: Path, exif: dict, p: dict, *, half: bool, log=print):
    """디코딩 + 카메라 톤 맞추기(RAW, camera_match) + 렌즈 보정. 렌즈 보정은 RAW만 기본으로 켠다."""
    lin, meta = decode.decode(path, half=half)
    if meta.is_raw and p.get("camera_match"):
        from . import camera
        lin = camera.apply(lin, camera.fit_lut(path, lin, log=log))
    if p.get("lens", meta.is_raw):
        lin = lens.correct(lin, exif, log=log)
    return lin, meta


def stage_geometry(lin, meta, p: dict, *, work_edge: int | None, device: str, log=print):
    """회전·크롭 → (작업 크기로 축소) → AI 노이즈 제거.
    반환: (lin, 회전 각도, scale=처리 해상도/원본 해상도)"""
    lin, angle = geometry.apply(lin, p)
    full_long = max(lin.shape[:2]) / meta.decode_scale
    if work_edge:
        lin = color.resize_long(lin, work_edge)
    scale = max(lin.shape[:2]) / full_long
    if p.get("ai_denoise"):
        from ai import denoise
        lin = denoise.denoise_linear(lin, p["ai_denoise"].get("strength", 100), device, log=log)
    return lin, angle, scale


def needs_faces(p: dict) -> bool:
    return bool(p.get("auto") or skin.active(p.get("skin")))


def detect_faces(lin, meta):
    from ai import face
    return face.detect(tone.to_display(color.resize_long(lin, 1280), meta.is_raw))


def apply_auto(lin, meta, faces, p: dict, layers: tuple | None):
    """자동 보정을 가장 낮은 우선순위로 깔아 최종 값을 만든다. 반환: (p, auto_info)"""
    from ai import auto
    info = auto.compute(lin, meta, faces, brightness=p.get("auto_brightness") or 0)
    if layers:
        p = P.validate(combine_auto(info["params"], *layers), warn=lambda m: None)
    else:
        p = P.deep_merge(info["params"], p)
    return p, info


def render(lin, meta, p: dict, faces, scale: float, log=print):
    """톤 → 피부 → LUT → 디테일. 반환: sRGB 감마 float32."""
    lin = tone.apply_linear(lin, p, meta)
    g = tone.to_display(lin, meta.is_raw)
    del lin
    g = tone.apply_display(g, p)
    g = skin.apply(g, p.get("skin"), faces, log=log)
    g = lut.apply(g, p.get("lut"), log=log)
    g = detail.noise_reduction(g, p.get("noise_reduction"), scale)
    g = detail.sharpen(g, p.get("sharpening"), scale)
    g = detail.vignette(g, p.get("vignette"))
    return g


def finish(g, p: dict, target: int | None, *, output_sharpen: bool, seed: int):
    """크기 조정(+출력용 샤프닝) → 그레인."""
    if target and max(g.shape[:2]) > target:
        g = color.resize_long(g, int(target), cv2.INTER_AREA)
        if output_sharpen:
            g = detail.output_sharpen(g)
    return detail.grain(g, p.get("grain"), seed=seed)


def applied_summary(p: dict) -> dict:
    return {k: p[k] for k in SUMMARY_KEYS if p.get(k) not in (None, 0)}


def seed_for(path: Path) -> int:
    return zlib.crc32(Path(path).stem.encode())


# ---------- 전체 처리 ----------

def process(path: Path, settings: dict, exif: dict, *, preview: bool, out_dir: Path,
            size: int | None, quality: int, device: str, layers: tuple | None = None, log=print) -> dict:
    t0 = time.time()
    p = P.validate(settings, warn=lambda m: log("  " + m))

    lin, meta = stage_decode(path, exif, p, half=preview, log=log)
    lin, angle, scale = stage_geometry(lin, meta, p, work_edge=PREVIEW_EDGE if preview else None,
                                       device=device, log=log)
    faces = detect_faces(lin, meta) if needs_faces(p) else []
    auto_info = None
    if p.get("auto"):
        p, auto_info = apply_auto(lin, meta, faces, p, layers)
        log("  자동: " + ", ".join(auto_info["reasons"]))
    applied = applied_summary(p)
    if applied:
        log("  적용값: " + ", ".join(f"{k} {v}" for k, v in applied.items()))

    g = render(lin, meta, p, faces, scale, log=log)
    del lin
    target = PREVIEW_EDGE if preview else (size or p.get("size"))
    g = finish(g, p, target, output_sharpen=not preview, seed=seed_for(path))

    if preview:
        dst = out_dir / f"{path.stem}.jpg"
        export.save_jpeg(g, dst, 85)
    else:
        dst = export.unique_path(out_dir / f"{path.stem}_edit.jpg")
        export.save_jpeg(g, dst, p.get("quality", quality))
        export.copy_exif(path, dst, log=log)
        if p.get("gps"):
            export.write_gps(dst, p["gps"], log=log)
    return {
        "file": path.name, "output": str(dst), "size": [g.shape[1], g.shape[0]],
        "rotate_total": round(angle, 2), "faces": len(faces),
        "auto": auto_info["params"] if auto_info else None, "applied": applied,
        "seconds": round(time.time() - t0, 1),
    }


def info(path: Path, exif: dict) -> dict:
    """Claude Code가 사진을 이해하는 데 쓰는 요약 (EXIF, WB, 히스토그램, 얼굴, 수평, 자동 보정 제안)."""
    from ai import auto, face
    lin, meta = decode.decode(path, half=True)
    small = color.resize_long(lin, 1024)
    g = tone.to_display(small, meta.is_raw)
    lum = color.luminance(g)
    faces = face.detect(g)
    face_l = face.face_luminance(g, faces)
    t, tint = color.as_shot_temp_tint(meta)
    hist, _ = np.histogram(lum, bins=8, range=(0, 1))
    pct = lambda q: round(float(np.percentile(lum, q)), 3)
    lv = geometry.detect_level(lin)
    prof, why = lens.find_profile(exif) if meta.is_raw else (None, "JPG 등은 렌즈 보정 기본 끔")
    auto_res = auto.compute(lin, meta, faces)
    iso = exif.get("ISO")
    try:
        iso_n = int(iso)
    except (TypeError, ValueError):
        iso_n = None
    w, h = meta.full_size
    return {
        "file": path.name,
        "path": str(path),
        "type": "raw" if meta.is_raw else "jpeg/raster",
        "camera": f"{exif.get('Make', '')} {exif.get('Model', '')}".strip(),
        "lens": exif.get("LensModel") or exif.get("LensID"),
        "focal_length": exif.get("FocalLength"),
        "aperture": exif.get("FNumber"),
        "shutter": exif.get("ExposureTime"),
        "iso": iso_n if iso_n is not None else iso,
        "exposure_comp": exif.get("ExposureCompensation"),
        "datetime": exif.get("DateTimeOriginal"),
        "gps": exif.get("GPSPosition"),
        "size": [w, h],
        "orientation": "portrait" if h > w else "landscape",
        "white_balance": {"as_shot_temperature": t, "as_shot_tint": tint, "camera_setting": exif.get("WhiteBalance"),
                          **({} if meta.is_raw else {"note": "JPG: 현재 색 = 기준값, 색온도는 상대 조정"})},
        "histogram": {
            "note": "기본 렌더링(보정 전) 휘도, 0=검정 1=흰색",
            "mean": round(float(lum.mean()), 3),
            "p1": pct(1), "p10": pct(10), "p50": pct(50), "p90": pct(90), "p99": pct(99),
            "clipped_highlights_pct": round(float((lum > 0.98).mean() * 100), 2),
            "crushed_shadows_pct": round(float((lum < 0.02).mean() * 100), 2),
            "zones_8": [round(float(x) / lum.size * 100, 1) for x in hist],
            "rgb_mean": [round(float(x), 3) for x in g.reshape(-1, 3).mean(0)],
        },
        "faces": [
            {"bbox": [round(x, 3) for x in f["bbox"]], "luminance": None if math.isnan(l) else round(l, 3),
             "method": f["method"]}
            for f, l in zip(faces, face_l)
        ],
        "auto_level": lv,
        "lens_profile": f"{prof[1].maker} {prof[1].model}" if prof else None,
        "lens_profile_missing_reason": why,
        "auto_suggestion": auto_res["params"],
        "auto_reasons": auto_res["reasons"],
        "hints": ([f"ISO {iso_n}: ai_denoise 권장"] if iso_n and iso_n >= 6400 else [])
                 + (["얼굴 있음: portrait 프리셋, skin 항목 사용 가능"] if faces else []),
    }
