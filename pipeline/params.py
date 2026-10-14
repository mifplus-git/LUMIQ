"""보정값 스키마, 범위, 설정 병합.

항목 이름은 라이트룸 방식(snake_case). edit.json, 프리셋 YAML, 사진별 YAML,
CLI 옵션이 모두 같은 이름을 쓴다.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import yaml

# 프로그램(코드·기본 프리셋·LUT·모델). 앱 번들로 실행하면 번들 안이라 쓰지 않는다.
ROOT = Path(__file__).resolve().parent.parent
# 작업 데이터(previews/·.app_state.json·저장한 프리셋·LUT. 보정값은 사진 옆 .lumiq.json). 소스로 실행하면 ROOT,
# 앱 번들은 런처가 LUMIQ_DATA로 알려 준다 (tools/build_app.py가 이 프로젝트 폴더로 정함).
DATA = Path(os.environ["LUMIQ_DATA"]).expanduser() if os.environ.get("LUMIQ_DATA") else ROOT
PRESET_DIR = DATA / "presets"  # 프리셋 저장 위치
CONFIG_FILE = DATA / "settings.json"  # 앱 설정 중 보정 결과에 영향을 주는 것 (CLI도 같은 값을 쓴다)

HSL_BANDS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"]

# 숫자 항목 범위. 범위를 벗어난 값은 잘라내고 경고한다.
RANGES = {
    "temperature": (2000, 50000),
    "tint": (-150, 150),
    "exposure": (-5.0, 5.0),
    "auto_brightness": (-100, 100),
    "contrast": (-100, 100),
    "highlights": (-100, 100),
    "shadows": (-100, 100),
    "whites": (-100, 100),
    "blacks": (-100, 100),
    "texture": (-100, 100),
    "clarity": (-100, 100),
    "dehaze": (-100, 100),
    "vibrance": (-100, 100),
    "saturation": (-100, 100),
    "rotate": (-45.0, 45.0),
    "hsl.*.hue": (-100, 100),
    "hsl.*.saturation": (-100, 100),
    "hsl.*.luminance": (-100, 100),
    "color_grading.*.hue": (0, 360),
    "color_grading.*.saturation": (0, 100),
    "color_grading.*.luminance": (-100, 100),
    "color_grading.blending": (0, 100),
    "color_grading.balance": (-100, 100),
    "sharpening.amount": (0, 150),
    "sharpening.radius": (0.5, 3.0),
    "sharpening.detail": (0, 100),
    "sharpening.masking": (0, 100),
    "noise_reduction.luminance": (0, 100),
    "noise_reduction.color": (0, 100),
    "vignette.amount": (-100, 100),
    "vignette.midpoint": (0, 100),
    "grain.amount": (0, 100),
    "grain.size": (0, 100),
    "grain.roughness": (0, 100),
    "skin.brightness": (-100, 100),
    "skin.smooth": (0, 100),
    "skin.saturation": (-100, 100),
    "skin.warmth": (-100, 100),
    "lut.strength": (0, 100),
    "ai_denoise.strength": (0, 100),
    "size": (64, 20000),
    "quality": (1, 100),
    "gps.lat": (-90.0, 90.0),
    "gps.lon": (-180.0, 180.0),
    "rating": (0, 3),
}


def app_config() -> dict:
    """settings.json (예: {"camera_match_default": true}). 없거나 깨졌으면 빈 dict."""
    try:
        d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_app_config(**values) -> dict:
    d = {**app_config(), **values}
    CONFIG_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return d

# 앱과 함께 나오는 기본 프리셋 (앱에서 '삭제'하면 파일은 두고 목록에서만 숨긴다)
BUILTIN_PRESETS = {"portrait", "snap", "spring_cherry", "spring_park", "spring_cafe", "summer_beach", "summer_city",
                   "summer_valley", "summer_night", "autumn_foliage", "autumn_golden", "autumn_street", "winter_snow",
                   "winter_lights", "winter_cozy"}

# 사진마다 다른 값이거나 처리 옵션이라 프리셋(색감·톤)으로 저장하지 않는 항목
PHOTO_ONLY_KEYS = {"file", "preset", "xmp", "auto", "temperature", "tint", "exposure", "crop", "crop_center", "crop_rect",
                   "crop_orientation", "rotate", "rotate90", "flip", "auto_level", "lens", "ai_denoise",
                   "size", "quality", "gps", "rating", "camera_match"}

KNOWN_KEYS = {
    "file", "preset", "xmp", "auto", "auto_brightness", "temperature", "tint", "exposure", "contrast", "highlights",
    "shadows", "whites", "blacks", "tone_curve", "tone_curve_red", "tone_curve_green",
    "tone_curve_blue", "texture", "clarity", "dehaze", "vibrance", "saturation", "hsl",
    "color_grading", "sharpening", "noise_reduction", "vignette", "grain", "skin", "lut",
    "crop", "crop_center", "crop_orientation", "crop_rect", "rotate", "rotate90", "flip", "auto_level",
    "lens", "ai_denoise", "size", "quality", "gps", "rating", "camera_match",
}


def deep_merge(base: dict, over: dict) -> dict:
    """over의 값이 base를 덮어쓴다. dict는 재귀 병합."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _range_for(path: str):
    if path in RANGES:
        return RANGES[path]
    parts = path.split(".")
    if len(parts) == 3:
        return RANGES.get(f"{parts[0]}.*.{parts[2]}")
    return None


def validate(params: dict, warn=print) -> dict:
    """알 수 없는 항목은 경고, 범위 밖 숫자는 잘라낸다."""
    p = copy.deepcopy(params)
    for k in list(p):
        if k not in KNOWN_KEYS:
            warn(f"[경고] 알 수 없는 항목 무시: {k}")
            p.pop(k)

    def walk(d, prefix=""):
        for k, v in d.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".")
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                r = _range_for(path)
                if r and not (r[0] <= v <= r[1]):
                    nv = min(max(v, r[0]), r[1])
                    warn(f"[경고] {path}={v} 범위({r[0]}~{r[1]}) 밖 → {nv}")
                    d[k] = nv

    for band in list((p.get("hsl") or {})):
        if band not in HSL_BANDS:
            warn(f"[경고] 알 수 없는 HSL 색 무시: {band} (가능: {', '.join(HSL_BANDS)})")
            p["hsl"].pop(band)
    walk(p)
    if p.get("ai_denoise") is True:
        p["ai_denoise"] = {"strength": 100}
    elif p.get("ai_denoise") is False:
        p["ai_denoise"] = None
    if isinstance(p.get("lut"), str):
        p["lut"] = {"file": p["lut"], "strength": 100}
    return p


def load_file(path) -> dict:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text) or {}


def preset_files() -> dict[str, Path]:
    """이름 → 파일. 저장한 프리셋(DATA)이 앱에 든 기본 프리셋(ROOT)보다 우선."""
    out = {}
    for d in dict.fromkeys((ROOT / "presets", PRESET_DIR)):
        for f in d.glob("*.yaml"):
            out[f.stem] = f
    return out


def preset_path(name: str) -> Path:
    p = Path(name)
    if p.suffix.lower() in (".yaml", ".yml") and p.exists():
        return p
    return preset_files().get(name, PRESET_DIR / f"{name}.yaml")


def load_preset(name: str) -> dict:
    path = preset_path(name)
    if not path.exists():
        names = sorted(preset_files())
        raise SystemExit(f"프리셋 없음: {name} (사용 가능: {', '.join(names)})")
    data = load_file(path) or {}
    for k in ("name", "label", "description"):  # 설명용 머리 항목
        data.pop(k, None)
    return data


def preset_info(path) -> tuple[str, str]:
    """(앱에 보일 이름, 설명). label이 없으면 파일 이름."""
    try:
        data = load_file(path) or {}
    except Exception:
        data = {}
    return str(data.get("label") or Path(path).stem), str(data.get("description") or "")


def save_preset(name: str, params: dict, description: str = "") -> Path:
    data = {k: v for k, v in params.items() if k not in PHOTO_ONLY_KEYS and v is not None}
    return write_preset(name, data, description=description)


def write_preset(name: str, data: dict, label: str = "", description: str = "") -> Path:
    """presets/<name>.yaml로 쓴다 (머리: name · label · description, 그 아래 값)."""
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    path = PRESET_DIR / f"{name}.yaml"
    header = {"name": name}
    if label and label != name:
        header["label"] = label
    if description:
        header["description"] = description
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({**header, **data}, f, allow_unicode=True, sort_keys=False)
    return path


# 프리셋으로 가져올 때 빼는 사진별 항목 (크롭 비율·노출·WB는 프리셋에 있어도 되므로 남긴다)
IMPORT_DROP = {"file", "preset", "crop_center", "crop_rect", "gps", "rating"}


def preset_slug(text: str) -> str:
    """파일 이름 → 프리셋 이름 (영문 소문자·숫자·밑줄). 한글뿐이면 imported."""
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "imported"


def read_preset_file(src) -> tuple[dict, str, str, list[str]]:
    """가져올 프리셋 파일(LUMIQ .yaml/.yml 또는 라이트룸 .xmp) → (값, 앱에 보일 이름, 설명, 알림).
    알 수 없는 항목은 빼고 알림에 적는다. 값이 하나도 없으면 ValueError."""
    src = Path(src)
    notes: list[str] = []
    if src.suffix.lower() == ".xmp":
        from presets.xmp_reader import read_xmp
        data = read_xmp(src)
        label = str(data.pop("_name", "") or src.stem)
        description = "라이트룸 프리셋에서 가져옴"
        if data.get("_unsupported"):
            notes.append(f"{src.name}: 적용하지 못하는 부분 — {', '.join(data['_unsupported'])}")
    else:
        data = load_file(src)
        if not isinstance(data, dict):
            raise ValueError("프리셋 형식이 아닙니다 (항목: 값 목록이어야 함)")
        label = str(data.get("label") or src.stem)
        description = str(data.get("description") or "")
        for k in ("name", "label", "description"):
            data.pop(k, None)
    data = {k: v for k, v in data.items() if not k.startswith("_") and k not in IMPORT_DROP and v is not None}
    data = validate(data, warn=lambda m: notes.append(f"{src.name}: {m.replace('[경고] ', '')}"))
    if not data:
        raise ValueError("가져올 보정값이 없습니다")
    return data, label, description, notes
