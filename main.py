#!/usr/bin/env python3
"""LUMIQ Studio CLI: 니콘 Z6 NEF(및 JPG/HEIC/PNG/WebP/TIFF) 보정 스크립트.

  python main.py ~/Photos/0901 --preset portrait --size 2048
  python main.py DSC_1234.NEF --exposure +0.3 --wb 5200
  python main.py ~/Photos/0901 --xmp ~/presets/film.xmp --auto --ai-denoise

Claude Code 연동 (보정값은 사진 옆 <사진 파일 이름>.lumiq.json, 예: DSC_1236.NEF.lumiq.json — 자동으로 적용):
  python main.py ~/Photos/0901 --info                          # 사진 정보 JSON
  python main.py ~/Photos/0901/DSC_1236.NEF --preview          # 1024px 미리보기 → previews/
  python main.py ~/Photos/0901 --size 2048 --out ~/Photos/0901/export
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# MediaPipe/TFLite 로그 줄이기
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from pipeline import params as P  # noqa: E402
from pipeline import files as files_mod  # noqa: E402

DATA = P.DATA  # 작업 데이터 폴더 (소스로 실행하면 이 폴더)
PREVIEW_DIR = DATA / "previews"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="NEF 보정 → JPEG", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("input", nargs="?", help="NEF/JPG/HEIC 등 사진 파일 또는 폴더 (생략 시 --params의 사진)")
    ap.add_argument("--with-jpeg", action="store_true", help="RAW+JPEG 쌍의 JPG도 처리 (기본은 RAW만)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="하위 폴더의 사진까지 (export/·숨김 폴더 제외). --out을 주면 그 안에 같은 하위 폴더 구조로 저장")
    g = ap.add_argument_group("연동")
    g.add_argument("--info", action="store_true", help="EXIF·WB·히스토그램·얼굴·자동 보정 제안을 JSON으로 출력")
    g.add_argument("--preview", action="store_true", help=f"긴 변 1024px 미리보기를 {PREVIEW_DIR.name}/에 저장")
    g.add_argument("--params", help="보정값 JSON/YAML 파일 또는 폴더. 생략하면 사진 옆 <사진 파일 이름>.lumiq.json")
    g.add_argument("--only", help="일괄 처리 중 일부만: DSC_1236,DSC_1240")
    g.add_argument("--verbose", action="store_true", help="--info를 여러 장일 때도 전체 항목으로 출력")
    g = ap.add_argument_group("프리셋·자동")
    g.add_argument("--preset", help="presets/<이름>.yaml")
    g.add_argument("--xmp", help="라이트룸 .xmp 프리셋")
    g.add_argument("--auto", action="store_true", default=None, help="원클릭 자동 보정")
    g.add_argument("--ai-denoise", action="store_true", default=None, help="AI 노이즈 제거 (SCUNet)")
    g.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto", help="AI 연산 장치")
    g.add_argument("--save-preset", metavar="이름", help="현재 설정을 presets/<이름>.yaml로 저장")
    g = ap.add_argument_group("보정값")
    g.add_argument("--exposure", type=float)
    g.add_argument("--wb", "--temperature", dest="temperature", type=float, help="색온도 K")
    g.add_argument("--tint", type=float)
    for k in ("contrast", "highlights", "shadows", "whites", "blacks", "texture", "clarity",
              "dehaze", "vibrance", "saturation"):
        g.add_argument(f"--{k}", type=float)
    g.add_argument("--lut", help=".cube 파일")
    g.add_argument("--lut-strength", type=float, help="LUT 강도 0~100")
    g.add_argument("--set", action="append", default=[], metavar="키=값",
                   help="임의 항목 지정, 예: --set skin.smooth=20 --set hsl.blue.saturation=-10")
    g = ap.add_argument_group("회전·크롭")
    g.add_argument("--rotate90", choices=["cw", "ccw", "180"])
    g.add_argument("--flip", choices=["h", "v"])
    g.add_argument("--rotate", type=float, help="각도(°), +가 시계 방향, 자동 수평값에 더함")
    g.add_argument("--crop", help="3:2, 4:5, 1:1, 16:9 …")
    g.add_argument("--no-auto-level", action="store_true")
    g.add_argument("--no-lens", action="store_true", help="렌즈 보정 끄기")
    g = ap.add_argument_group("Export")
    g.add_argument("--size", type=int, help="긴 변 px (기본 원본)")
    g.add_argument("--quality", type=int, default=92)
    g.add_argument("--out", help="출력 폴더 (기본: 원본 폴더/export)")
    return ap.parse_args(argv)


def _set_path(d: dict, dotted: str, value):
    keys = dotted.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _parse_value(v: str):
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        return v


def cli_layer(a) -> dict:
    d = {}
    for k in ("preset", "xmp", "auto", "exposure", "temperature", "tint", "contrast", "highlights", "shadows",
              "whites", "blacks", "texture", "clarity", "dehaze", "vibrance", "saturation", "rotate90", "flip",
              "rotate", "crop", "size"):
        v = getattr(a, k, None)
        if v is not None:
            d[k] = v
    if a.ai_denoise:
        d["ai_denoise"] = True
    if a.lut:
        d["lut"] = {"file": a.lut}
    if a.lut_strength is not None:
        d.setdefault("lut", {})["strength"] = a.lut_strength
    if a.no_auto_level:
        d["auto_level"] = False
    if a.no_lens:
        d["lens"] = False
    if a.quality != 92:
        d["quality"] = a.quality
    for item in a.set:
        if "=" not in item:
            sys.exit(f"--set 형식 오류: {item} (키=값)")
        k, v = item.split("=", 1)
        _set_path(d, k.strip(), _parse_value(v.strip()))
    return d


class ParamsSource:
    """보정값 출처. 기본은 사진 옆 <사진 파일 이름>.lumiq.json.
    --params: 파일(dict 또는 list, .lumiq.json이면 그 사진) 또는 폴더(<사진 파일 이름>.lumiq.json / 예전 <stem>.json·.yaml)."""

    def __init__(self, spec: str | None):
        self.dir = None
        self.entries: list[dict] = []
        self.base = Path.cwd()
        self.sidecar_only = not spec
        if not spec:
            return
        p = Path(spec).expanduser()
        if not p.exists() and not p.is_absolute() and (DATA / p).exists():
            p = DATA / p  # 작업 폴더 밖에서 앱의 CLI를 불러도 작업 폴더 기준 경로를 찾도록
        if p.is_dir():
            self.dir = p
        elif p.exists():
            self.base = p.parent
            data = P.load_file(p)
            self.entries = data if isinstance(data, list) else [data]
            if files_mod.is_edit_file(p) and isinstance(data, dict) and not data.get("file"):
                self.entries = [{**data, "file": str(files_mod.photo_for_edit(p))}]  # 이름이 곧 사진
        else:
            sys.exit(f"--params 경로 없음: {spec}")

    def for_photo(self, path: Path) -> dict:
        if self.sidecar_only:
            return files_mod.load_edit(path)
        if self.dir:
            f = self.dir / (path.name + files_mod.SIDECAR)
            if not f.exists():
                f = files_mod.find_legacy_edit(path, self.dir)  # 예전 방식: file 경로가 같은 것 우선, 없으면 이름으로
            if f:
                return P.load_file(f) or {}
            for ext in (".yaml", ".yml"):
                f = self.dir / f"{path.stem}{ext}"
                if f.exists():
                    return P.load_file(f) or {}
            return {}
        out = {}
        for e in self.entries:
            f = e.get("file")
            if not f or Path(f).stem == path.stem:
                out = P.deep_merge(out, e)
        return out

    def files(self) -> list[Path]:
        found = []
        entries = self.entries
        if self.dir:
            entries = []
            for f in sorted(self.dir.glob("*.json")):
                e = P.load_file(f)
                if files_mod.is_edit_file(f) and isinstance(e, dict) and not e.get("file"):
                    e = {**e, "file": str(files_mod.photo_for_edit(f))}
                entries.append(e)
        for e in entries:
            f = e.get("file") if isinstance(e, dict) else None
            if not f:
                continue
            for cand in (Path(f).expanduser(), self.base / f, Path.cwd() / f):
                if cand.exists():
                    found.append(cand.absolute())
                    break
            else:
                sys.exit(f"사진을 찾을 수 없음: {f} (보정값 파일은 사진 옆에 <사진 파일 이름>.lumiq.json으로 두세요)")
        return found


def collect_inputs(a, src: ParamsSource) -> list[Path]:
    if a.input:
        p = Path(a.input).expanduser()
        if p.is_dir():
            files = files_mod.collect_images(p, include_paired_jpeg=a.with_jpeg, recursive=a.recursive)
        elif p.exists():
            files = [p]
        else:
            sys.exit(f"입력 없음: {a.input}")
    else:
        files = src.files()
    if a.only:
        keep = {s.strip().rsplit(".", 1)[0] for s in a.only.split(",")}
        files = [f for f in files if f.stem in keep]
    return [f.absolute() for f in files]  # resolve()는 심볼릭 링크 이름을 바꾸므로 쓰지 않음


def _brief(info: dict) -> dict:
    h = info["histogram"]
    return {
        "file": info["file"], "iso": info["iso"], "shutter": info["shutter"], "aperture": info["aperture"],
        "focal_length": info["focal_length"], "orientation": info["orientation"],
        "wb": [info["white_balance"]["as_shot_temperature"], info["white_balance"]["as_shot_tint"]],
        "hist": {k: h[k] for k in ("mean", "p1", "p50", "p99", "clipped_highlights_pct", "crushed_shadows_pct")},
        "faces": [f["bbox"] + [f["luminance"]] for f in info["faces"]],
        "level": info["auto_level"]["angle"],
        "auto": info["auto_suggestion"],
        "hints": info["hints"],
    }


def main(argv=None):
    a = parse_args(argv)
    src = ParamsSource(a.params)
    cli = cli_layer(a)
    if cli.get("preset"):
        P.load_preset(cli["preset"])  # 명령에 직접 준 프리셋이 없으면 바로 멈춘다
    files = collect_inputs(a, src) if (a.input or a.params) else []
    base = Path(a.input).expanduser().absolute() if a.input and Path(a.input).expanduser().is_dir() else None

    from pipeline import export, runner

    if a.save_preset:
        if files:
            merged, _ = runner.settings_for(files[0], {"cli": cli, "params_for": src.for_photo})
        else:
            merged = P.deep_merge(P.load_preset(cli["preset"]) if cli.get("preset") else {},
                                  P.deep_merge(src.entries[0] if src.entries else {}, cli))
        merged = P.validate(merged, warn=print)
        path = P.save_preset(a.save_preset, merged)
        print(f"프리셋 저장: {path.relative_to(DATA)}")
        if not (a.preview or a.info or a.size or a.out):
            return

    if not files:
        sys.exit("처리할 사진이 없습니다. NEF 파일/폴더나 --params를 지정하세요.")

    exif_all = export.read_exif(files)

    if a.info:
        results = []
        for f in files:
            try:
                results.append(runner.info(f, exif_all.get(str(f), {})))
            except Exception as e:
                results.append({"file": f.name, "error": str(e)})
        if len(results) == 1:
            print(json.dumps(results[0], ensure_ascii=False, indent=1, default=str))
        else:
            rows = results if a.verbose else [r if "error" in r else _brief(r) for r in results]
            print(json.dumps({"count": len(rows), "photos": rows}, ensure_ascii=False, default=str))
        return

    out_default = PREVIEW_DIR if a.preview else None
    ok = fail = 0
    for i, f in enumerate(files, 1):
        settings, origin = runner.settings_for(f, {"cli": cli, "params_for": src.for_photo})
        out_dir = out_default or files_mod.export_dir_for(f, Path(a.out).expanduser() if a.out else None, base)
        tag = " ".join(k for k, v in origin.items() if v and k != "layers")
        print(f"[{i}/{len(files)}] {f.name}" + (f" ({tag})" if tag else ""))
        try:
            r = runner.process(f, settings, exif_all.get(str(f), {}), preview=a.preview, out_dir=out_dir,
                               size=a.size, quality=a.quality, device=a.device, layers=origin.pop("layers"))
            print(f"  → {r['output']} ({r['size'][0]}×{r['size'][1]}, {r['seconds']}s)")
            ok += 1
        except Exception as e:
            print(f"  실패: {type(e).__name__}: {e}")
            fail += 1
    print(f"완료 {ok}장" + (f", 실패 {fail}장" if fail else ""))
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
