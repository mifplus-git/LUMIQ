"""사진 목록과 보정값 파일 (CLI, 앱, Claude Code가 함께 쓴다).

보정값(보정·별점·위치)은 사진 바로 옆 <사진 파일 이름>.lumiq.json에 둔다 (예: DSC_1236.NEF.lumiq.json).
사진과 함께 옮기면 보정값도 따라가고, 사진마다 파일이 따로라 앱과 Claude Code가 동시에 고쳐도 서로 덮어쓰지 않는다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .decode import IMAGE_EXTS, RAW_EXTS
from .params import DATA

SIDECAR = ".lumiq.json"  # 보정값 파일 꼬리: DSC_1236.NEF → DSC_1236.NEF.lumiq.json
LEGACY_EDITS_DIR = DATA / "edits"  # 예전 저장 위치 (migrate_legacy_edits가 사진 옆으로 옮긴다)
# 하위 폴더를 훑을 때 건너뛰는 폴더: 내보낸 결과, 숨김 폴더, NAS·압축 부산물, 사진 앱 라이브러리 같은 패키지
SKIP_DIRS = {"export", "@eaDir", "__MACOSX", "$RECYCLE.BIN", "System Volume Information"}
SKIP_DIR_SUFFIXES = (".photoslibrary", ".photolibrary", ".aplibrary", ".migratedphotolibrary", ".lrdata",
                     ".lrlibrary", ".cocatalog", ".cocatalogdb", ".app", ".bundle")


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS or name.lower().endswith(SKIP_DIR_SUFFIXES)


def collect_images(folder: Path, include_paired_jpeg: bool = False, recursive: bool = False,
                   limit: int | None = None) -> list[Path]:
    """폴더의 사진 목록. RAW+JPEG로 찍은 쌍은 기본으로 RAW만 남긴다.
    recursive면 하위 폴더까지 (export/·숨김 폴더 제외), 폴더별로 묶어 정렬한다.
    limit을 넘으면 거기서 멈춘다 (너무 큰 폴더를 실수로 열었을 때 확인용)."""
    folder = Path(folder).absolute()
    files = []

    def onerror(e: OSError):
        if Path(e.filename) == folder:  # 연 폴더 자체를 못 읽으면 알린다 (하위 폴더 오류는 건너뜀)
            raise e
    for dirpath, dirnames, filenames in os.walk(folder, onerror=onerror):
        dirnames[:] = [] if not recursive else sorted(d for d in dirnames if not _skip_dir(d))
        d = Path(dirpath)
        files += [d / n for n in filenames
                  if not n.startswith(".") and os.path.splitext(n)[1].lower() in IMAGE_EXTS]
        if limit is not None and len(files) > limit:
            break
    files = [f for f in files if f.is_file()]
    if not include_paired_jpeg:  # 쌍은 같은 폴더 안에서만 찾는다
        raw_keys = {(f.parent, f.stem) for f in files if f.suffix.lower() in RAW_EXTS}
        files = [f for f in files if f.suffix.lower() in RAW_EXTS or (f.parent, f.stem) not in raw_keys]

    def key(p: Path):
        rel = p.parent.relative_to(folder)
        return [s.lower() for s in rel.parts], p.name.lower()  # 폴더 바로 아래 사진이 먼저
    return sorted(files, key=key)


def _same(a, b) -> bool:
    try:
        return Path(a).expanduser().absolute() == Path(b).expanduser().absolute()
    except (TypeError, ValueError):
        return False


def edit_path_for(photo: Path) -> Path:
    """이 사진의 보정값 파일 경로 (없어도 이 이름으로 만든다)."""
    photo = Path(photo).expanduser().absolute()
    return photo.with_name(photo.name + SIDECAR)


def find_edit(photo: Path) -> Path | None:
    p = edit_path_for(photo)
    return p if p.is_file() else None


def is_edit_file(f: Path) -> bool:
    return Path(f).name.endswith(SIDECAR) and len(Path(f).name) > len(SIDECAR)


def photo_for_edit(f: Path) -> Path:
    """보정값 파일 → 사진 경로 (DSC_1236.NEF.lumiq.json → DSC_1236.NEF)."""
    f = Path(f).expanduser().absolute()
    return f.with_name(f.name[:-len(SIDECAR)])


def edit_files_in(dirs) -> list[Path]:
    """폴더들에 있는 보정값 파일 (하위 폴더는 보지 않음)."""
    out = []
    for d in dirs:
        try:
            out += [f for f in Path(d).glob("*" + SIDECAR) if f.is_file()]
        except OSError:
            pass
    return out


def load_edit(photo: Path) -> dict:
    p = find_edit(photo)
    if not p:
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_edit(photo: Path, edit: dict) -> Path:
    """보정값을 사진 옆 파일에 쓴다. 남은 값이 없으면 빈 파일을 남기지 않고 지운다."""
    path = edit_path_for(photo)
    data = {k: v for k, v in edit.items() if k != "file"}
    if not data:
        path.unlink(missing_ok=True)
        return path
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def find_legacy_edit(photo: Path, edits_dir: Path = LEGACY_EDITS_DIR) -> Path | None:
    """예전 방식(한 폴더에 <파일명>.json)의 보정값 파일. file 경로가 같은 것 우선, file이 없으면 이름으로."""
    photo = Path(photo).absolute()
    if not edits_dir.exists():
        return None
    candidates = [edits_dir / f"{photo.stem}.json", edits_dir / f"{photo.stem}_{photo.suffix[1:].lower()}.json"]
    candidates += sorted(edits_dir.glob(f"{photo.stem}*.json"))
    seen = set()
    fallback = None
    for c in candidates:
        if c in seen or not c.exists() or is_edit_file(c):
            continue
        seen.add(c)
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        f = data.get("file") if isinstance(data, dict) else None
        if f and _same(f, photo):
            return c
        if not f and c.stem == photo.stem and fallback is None:
            fallback = c
    return fallback


def migrate_legacy_edits(edits_dir: Path = LEGACY_EDITS_DIR) -> tuple[list[str], list[str]]:
    """예전 edits/*.json을 사진 옆 <사진 파일 이름>.lumiq.json으로 옮긴다. 반환: (옮긴 사진 이름, 남긴 파일 이름).
    사진을 찾지 못했거나 그 폴더에 쓸 수 없으면 그대로 남긴다. 옮긴 뒤 빈 edits/ 폴더는 지운다."""
    moved, left = [], []
    if not edits_dir.is_dir():
        return moved, left
    for f in sorted(edits_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            left.append(f.name)
            continue
        photo = Path(data["file"]).expanduser() if isinstance(data, dict) and data.get("file") else None
        if photo is None or not photo.is_file():
            left.append(f.name)
            continue
        data.pop("file")
        dst = edit_path_for(photo)
        try:
            if dst.exists():  # 이미 사진 옆에 있으면 그쪽이 최신이다
                if json.loads(dst.read_text(encoding="utf-8")) != data:
                    left.append(f.name)
                    continue
            elif data:
                save_edit(photo, data)
                if json.loads(dst.read_text(encoding="utf-8")) != data:
                    raise OSError("확인 실패")
            f.unlink()
            moved.append(photo.name)
        except (OSError, json.JSONDecodeError):
            left.append(f.name)
    try:
        if not any(edits_dir.iterdir()):
            edits_dir.rmdir()
    except OSError:
        pass
    return moved, left


def has_adjustments(edit: dict) -> bool:
    """보정값이 하나라도 있는지 (위치 gps와 별점 rating은 보정이 아니라 제외)."""
    return any(k not in ("file", "gps", "rating") for k in edit)


def export_dir_for(photo: Path, out_dir: Path | None, base: Path | None = None) -> Path:
    """내보낼 폴더. 기본(None)은 사진 폴더의 export/. out_dir을 정했으면 base 기준 하위 폴더 구조를 그 안에 유지한다."""
    photo = Path(photo)
    if out_dir is None:
        return photo.parent / "export"
    if base is not None:
        try:
            return Path(out_dir) / photo.parent.relative_to(base)
        except ValueError:
            pass
    return Path(out_dir)


def exported_files(photo: Path, out_dir: Path) -> list[Path]:
    if not out_dir.exists():
        return []
    stem = Path(photo).stem
    return sorted(out_dir.glob(f"{stem}_edit*.jpg"))
