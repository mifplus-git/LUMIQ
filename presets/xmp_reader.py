"""라이트룸 .xmp 프리셋 읽기: crs: 값을 파이프라인 파라미터(라이트룸 방식 이름)로 변환.

프로파일(내장 LUT), 마스크 같은 부분 보정은 지원하지 않는다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

SIMPLE = {
    "Temperature": "temperature", "Tint": "tint",
    "Exposure2012": "exposure", "Exposure": "exposure",
    "Contrast2012": "contrast", "Highlights2012": "highlights", "Shadows2012": "shadows",
    "Whites2012": "whites", "Blacks2012": "blacks",
    "Texture": "texture", "Clarity2012": "clarity", "Clarity": "clarity", "Dehaze": "dehaze",
    "Vibrance": "vibrance", "Saturation": "saturation",
}
NESTED = {
    "Sharpness": ("sharpening", "amount"), "SharpenRadius": ("sharpening", "radius"),
    "SharpenDetail": ("sharpening", "detail"), "SharpenEdgeMasking": ("sharpening", "masking"),
    "LuminanceSmoothing": ("noise_reduction", "luminance"), "ColorNoiseReduction": ("noise_reduction", "color"),
    "PostCropVignetteAmount": ("vignette", "amount"), "PostCropVignetteMidpoint": ("vignette", "midpoint"),
    "PostCropVignetteFeather": ("vignette", "feather"),
    "GrainAmount": ("grain", "amount"), "GrainSize": ("grain", "size"), "GrainFrequency": ("grain", "roughness"),
    "ColorGradeBlending": ("color_grading", "blending"), "ColorGradeBalance": ("color_grading", "balance"),
}
HSL_NAMES = {"Red": "red", "Orange": "orange", "Yellow": "yellow", "Green": "green",
             "Aqua": "aqua", "Blue": "blue", "Purple": "purple", "Magenta": "magenta"}
HSL_KIND = {"HueAdjustment": "hue", "SaturationAdjustment": "saturation", "LuminanceAdjustment": "luminance"}
CG_ZONE = {"Shadow": "shadows", "Midtone": "midtones", "Highlight": "highlights", "Global": "global"}
CG_KIND = {"Hue": "hue", "Sat": "saturation", "Lum": "luminance"}
CURVES = {"ToneCurvePV2012": "tone_curve", "ToneCurvePV2012Red": "tone_curve_red",
          "ToneCurvePV2012Green": "tone_curve_green", "ToneCurvePV2012Blue": "tone_curve_blue"}


def _num(v: str):
    v = v.strip()
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f.is_integer() and "." not in v else f


def _collect(path) -> tuple[dict, dict, set]:
    """(단순 속성 dict, rdf:Seq 리스트 dict, crs 요소 이름들)"""
    root = ET.parse(path).getroot()
    attrs, seqs, tags = {}, {}, set()
    for el in root.iter():
        for k, v in el.attrib.items():
            if k.startswith("{" + CRS + "}"):
                attrs[k[len(CRS) + 2:]] = v
        if el.tag.startswith("{" + CRS + "}"):
            name = el.tag[len(CRS) + 2:]
            tags.add(name)
            items = [li.text or "" for li in el.iter("{" + RDF + "}li")]
            if items:
                seqs[name] = items
            elif el.text and el.text.strip():
                attrs[name] = el.text.strip()
    return attrs, seqs, tags


def read_xmp(path) -> dict:
    attrs, seqs, tags = _collect(path)
    p: dict = {}
    for k, v in attrs.items():
        n = _num(v)
        if k in SIMPLE and n is not None:
            p[SIMPLE[k]] = n
        elif k in NESTED and n is not None:
            grp, key = NESTED[k]
            p.setdefault(grp, {})[key] = n
        elif n is not None:
            m = re.fullmatch(r"(HueAdjustment|SaturationAdjustment|LuminanceAdjustment)(\w+)", k)
            if m and m.group(2) in HSL_NAMES:
                p.setdefault("hsl", {}).setdefault(HSL_NAMES[m.group(2)], {})[HSL_KIND[m.group(1)]] = n
                continue
            m = re.fullmatch(r"ColorGrade(Shadow|Midtone|Highlight|Global)(Hue|Sat|Lum)", k)
            if m:
                p.setdefault("color_grading", {}).setdefault(CG_ZONE[m.group(1)], {})[CG_KIND[m.group(2)]] = n
    # 예전 스플릿 토닝 → 컬러 그레이딩
    if "SplitToningShadowSaturation" in attrs and "color_grading" not in p:
        cg = p.setdefault("color_grading", {})
        cg["shadows"] = {"hue": _num(attrs.get("SplitToningShadowHue", "0")),
                         "saturation": _num(attrs["SplitToningShadowSaturation"])}
        cg["highlights"] = {"hue": _num(attrs.get("SplitToningHighlightHue", "0")),
                            "saturation": _num(attrs.get("SplitToningHighlightSaturation", "0"))}
        if "SplitToningBalance" in attrs:
            cg["balance"] = _num(attrs["SplitToningBalance"])
    for k, key in CURVES.items():
        pts = []
        for item in seqs.get(k, []):
            xy = [_num(x) for x in item.split(",")]
            if len(xy) == 2 and None not in xy:
                pts.append(xy)
        if len(pts) >= 2 and pts != [[0, 0], [255, 255]]:
            p[key] = pts
    # 라이트룸은 노이즈 감소 기본값이 0이 아니어도 RAW에서만 의미 있음. 0인 그룹은 제거
    for grp in ("sharpening", "noise_reduction", "vignette", "grain"):
        if grp in p and not any(v for k, v in p[grp].items() if k in ("amount", "luminance", "color")):
            p.pop(grp)
    if attrs.get("WhiteBalance") in ("As Shot", "Auto"):
        p.pop("temperature", None)
        p.pop("tint", None)
    unsupported = []
    if "Look" in tags or attrs.get("LookTable"):
        unsupported.append("프로파일/룩(내장 LUT)")
    if tags & {"MaskGroupBasedCorrections", "GradientBasedCorrections", "CircularGradientBasedCorrections",
               "PaintBasedCorrections"}:
        unsupported.append("마스크 부분 보정")
    if unsupported:
        p["_unsupported"] = unsupported
    name = (seqs.get("Name") or [attrs.get("Name", "")])[0].strip()  # 라이트룸 프리셋 이름 (crs:Name)
    if name:
        p["_name"] = name
    return p


if __name__ == "__main__":
    import json
    import sys
    for f in sys.argv[1:]:
        print(Path(f).name, json.dumps(read_xmp(f), ensure_ascii=False, indent=2))
