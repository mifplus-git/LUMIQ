"""위치(GPS) 추가: 좌표 읽기와 입력 창.

원본 파일은 바꾸지 않는다. 위치는 사진 옆 보정값 파일(.lumiq.json)의 "gps"({"lat", "lon", "name"})에 저장되고
내보낼 때 JPEG의 EXIF GPS로 기록된다 (pipeline/export.write_gps).
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from . import theme as T

RECENT_KEY = "gps/recent"
MAX_RECENT = 10
_NUM = r"(\d+(?:[.,]\d+)?)"
# 37°33'59.4"N · 37 deg 33' 59.40" N · N 37° 33.99' · 37.5665° N
_DMS = re.compile(r"([NSEW])?\s*" + _NUM + r"\s*(?:°|º|deg|도)\s*(?:" + _NUM + r"\s*(?:'|′|’|분)\s*)?"
                  r"(?:" + _NUM + r"\s*(?:\"|″|''|”|초)\s*)?(?(1)|([NSEW])?)", re.I)  # 반구 글자는 앞이나 뒤 한쪽만
_PAIR = re.compile(r"(-?\d{1,3}(?:\.\d+)?)\s*[,/ ]\s*(-?\d{1,3}(?:\.\d+)?)")
_URL_KEYS = re.compile(r"(?:!3d(-?\d+\.\d+)!4d(-?\d+\.\d+))|(?:@(-?\d+\.\d+),(-?\d+\.\d+))|"
                       r"(?:[?&](?:ll|q|query|coordinate|center|sll)=(-?\d+\.\d+)(?:,|%2C)\s*(-?\d+\.\d+))", re.I)
_KO_HEMI = {"북위": "N", "남위": "S", "동경": "E", "서경": "W"}


def _valid(lat: float, lon: float) -> tuple[float, float] | None:
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return round(lat, 6), round(lon, 6)
    return None


def parse_coords(text: str) -> tuple[float, float] | None:
    """지도 앱에서 복사한 좌표·링크를 (위도, 경도)로. 못 읽으면 None.
    37.5665, 126.978 / 37°33'59.4"N 126°58'40.8"E / 북위 37.5665 동경 126.978 / Google·Apple 지도 링크"""
    if not text or not text.strip():
        return None
    s = text.strip()
    m = _URL_KEYS.search(s)
    if m:
        a, b = [g for g in m.groups() if g is not None][:2]
        return _valid(float(a), float(b))
    for ko, hemi in _KO_HEMI.items():
        s = s.replace(ko, hemi + " ")
    parts = []
    for m in _DMS.finditer(s):
        pre, d, mi, se, post = m.groups()
        v = float(d.replace(",", ".")) + float((mi or "0").replace(",", ".")) / 60 + \
            float((se or "0").replace(",", ".")) / 3600
        parts.append((v, (pre or post or "").upper()))
    if len(parts) >= 2:
        lat = lon = None
        for v, hemi in parts[:2]:
            if hemi in ("N", "S"):
                lat = -v if hemi == "S" else v
            elif hemi in ("E", "W"):
                lon = -v if hemi == "W" else v
        if lat is None and lon is None:
            lat, lon = parts[0][0], parts[1][0]
        if lat is not None and lon is not None:
            return _valid(lat, lon)
    # 반구 글자만 붙은 소수: "N 37.5665 E 126.978", "37.5665N 126.978E"
    hemi = re.findall(r"([NSEW])?\s*(\d+\.\d+)\s*(?(1)|([NSEW])?)", s, re.I)
    if len(hemi) >= 2 and all(a or c for a, _, c in hemi[:2]):
        vals = {}
        for a, v, c in hemi[:2]:
            h = (a or c).upper()
            vals["lat" if h in "NS" else "lon"] = -float(v) if h in "SW" else float(v)
        if len(vals) == 2:
            return _valid(vals["lat"], vals["lon"])
    m = _PAIR.search(s)
    if m:
        return _valid(float(m.group(1)), float(m.group(2)))
    return None


def format_coords(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}"


def describe(lat: float, lon: float) -> str:
    return (f"{'북위' if lat >= 0 else '남위'} {abs(lat):.5f}°  ·  "
            f"{'동경' if lon >= 0 else '서경'} {abs(lon):.5f}°")


def gps_label(gps: dict | None) -> str:
    """정보 줄·메뉴에 보일 짧은 이름: 장소 이름이 있으면 그것, 없으면 좌표."""
    if not isinstance(gps, dict) or gps.get("lat") is None or gps.get("lon") is None:
        return ""
    return str(gps.get("name") or f"{float(gps['lat']):.4f}, {float(gps['lon']):.4f}")


def load_recent(settings: QSettings) -> list[dict]:
    try:
        data = json.loads(settings.value(RECENT_KEY, "[]") or "[]")
    except (TypeError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and "lat" in d and "lon" in d]


def remember(settings: QSettings, gps: dict):
    items = [d for d in load_recent(settings)
             if (round(d["lat"], 5), round(d["lon"], 5)) != (round(gps["lat"], 5), round(gps["lon"], 5))]
    settings.setValue(RECENT_KEY, json.dumps([gps] + items[:MAX_RECENT - 1], ensure_ascii=False))


class LocationDialog(QDialog):
    """위치 추가·수정. 결과: self.result_gps (dict, 지우기면 None)."""
    REMOVE = 2

    def __init__(self, parent, title: str, subtitle: str, current: dict | None, sources: list[tuple[str, dict]],
                 recent: list[dict], n_total: int, n_original: int, can_remove: bool):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.result_gps: dict | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        head = QLabel(title)
        head.setObjectName("Title")
        sub = QLabel(subtitle)
        sub.setObjectName("Muted")
        lay.addWidget(head)
        lay.addWidget(sub)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.coords = QLineEdit()
        self.coords.setObjectName("Field")
        self.coords.setPlaceholderText("37.5665, 126.9780  ·  지도에서 복사한 좌표나 링크")
        self.coords.textChanged.connect(self._update)
        form.addRow("좌표", self.coords)
        self.parsed = QLabel(" ")
        self.parsed.setObjectName("Faint")
        form.addRow("", self.parsed)
        self.name = QLineEdit()
        self.name.setObjectName("Field")
        self.name.setPlaceholderText("선택 · 예: 제주 협재해변")
        form.addRow("장소 이름", self.name)
        self.pick = QComboBox()
        self.pick.addItem("최근 위치 · 사진에서 가져오기…", None)
        for d in recent:
            self.pick.addItem(f"최근  ·  {gps_label(d)}", d)
        if recent and sources:
            self.pick.insertSeparator(self.pick.count())
        for label, d in sources:
            self.pick.addItem(f"{label}의 위치  ·  {gps_label(d)}", d)
        self.pick.setEnabled(self.pick.count() > 1)
        self.pick.currentIndexChanged.connect(self._on_pick)
        form.addRow("가져오기", self.pick)
        lay.addLayout(form)

        row = QHBoxLayout()
        find = QPushButton("지도에서 찾기")
        find.setObjectName("Ghost")
        find.setToolTip("브라우저에서 Google 지도를 엽니다 (좌표나 장소 이름이 있으면 그 위치로)")
        find.clicked.connect(self._open_map)
        row.addWidget(find)
        tip = QLabel("지도에서 장소를 오른쪽 클릭 → 맨 위 좌표를 누르면 복사됩니다")
        tip.setObjectName("Faint")
        row.addWidget(tip, 1)
        lay.addLayout(row)

        text = "원본 파일은 바뀌지 않습니다. 위치는 보정값과 함께 저장되고, 내보낸 JPEG에 기록됩니다."
        if n_original:
            text += ("\n이 사진에는 원래 위치가 있어 내보낼 때 이 위치로 바뀝니다." if n_total == 1
                     else f"\n그중 원래 위치가 있는 {n_original}장은 내보낼 때 이 위치로 바뀝니다.")
        note = QLabel(text)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)

        bb = QHBoxLayout()
        if can_remove:
            rm = QPushButton("위치 지우기")
            rm.setObjectName("Ghost")
            rm.setToolTip("앱에서 추가한 위치를 지웁니다 (사진에 원래 있던 위치는 그대로)")
            rm.clicked.connect(lambda: self.done(self.REMOVE))
            bb.addWidget(rm)
        bb.addStretch(1)
        cancel = QPushButton("취소")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("적용")
        self.ok.setObjectName("Primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._accept)
        bb.addWidget(cancel)
        bb.addWidget(self.ok)
        lay.addLayout(bb)
        self.setMinimumWidth(540)
        if current:
            self.coords.setText(format_coords(float(current["lat"]), float(current["lon"])))
            self.name.setText(str(current.get("name") or ""))
        self._update()

    def _update(self, *_):
        c = parse_coords(self.coords.text())
        self.ok.setEnabled(c is not None)
        if c is not None:
            self.parsed.setText(describe(*c))
            self.parsed.setStyleSheet(f"color: {T.GOOD};")
        elif self.coords.text().strip():
            self.parsed.setText("좌표를 읽을 수 없습니다 (예: 37.5665, 126.9780)")
            self.parsed.setStyleSheet(f"color: {T.ACCENT_HI};")
        else:
            self.parsed.setText(" ")
            self.parsed.setStyleSheet("")

    def _on_pick(self, i: int):
        d = self.pick.itemData(i)
        if not isinstance(d, dict):
            return
        self.coords.setText(format_coords(float(d["lat"]), float(d["lon"])))
        self.name.setText(str(d.get("name") or ""))

    def _open_map(self):
        c = parse_coords(self.coords.text())
        q = f"{c[0]},{c[1]}" if c else self.name.text().strip()
        url = f"https://www.google.com/maps/search/?api=1&query={quote(q)}" if q else "https://www.google.com/maps"
        QDesktopServices.openUrl(QUrl(url))

    def _accept(self):
        c = parse_coords(self.coords.text())
        if c is None:
            return
        self.result_gps = {"lat": c[0], "lon": c[1]}
        if self.name.text().strip():
            self.result_gps["name"] = self.name.text().strip()
        self.accept()
