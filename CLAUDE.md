# LUMIQ Studio: Claude Code 사진 보정 규칙

LUMIQ — 빛을 이해하고, 사진을 완성하다. (LUMI = 빛과 이미지의 아름다움, Q = Quality)

니콘 Z6 NEF(및 JPG·HEIC·PNG·WebP·TIFF)를 보정해 JPEG로 내보내는 프로젝트. **보정 연산은 `main.py`(CLI)와
`LUMIQ Studio.app`(데스크톱 앱)이 Mac에서 로컬로 하고, Claude Code는 사진 분석·보정값 결정·재조정만 한다.**
스크립트와 앱에 API나 LLM 호출을 넣지 않는다.

- 실행: 항상 `.venv/bin/python main.py ...` (Python 3.12 arm64 venv, MPS 사용)
- 앱: 응용 프로그램의 `LUMIQ Studio` (`/Applications/LUMIQ Studio.app`) 또는 `.venv/bin/python app.py [폴더]`
  - 앱은 Python·패키지·코드·모델·exiftool을 모두 담은 **독립 번들**이라 이 폴더나 `.venv`, Homebrew 없이도 실행된다.
    작업 데이터(`previews/`·`.app_state.json`·저장한 프리셋)는 이 프로젝트 폴더를 그대로 쓴다 (없으면 앱이 만듦).
    보정값은 사진 옆 `.lumiq.json`에 있다 (아래 '보정값 파일')
  - 앱은 설치할 때의 코드 사본이다. 코드를 고친 뒤 앱에 반영하려면 `.venv/bin/python tools/build_app.py`를 다시 실행
    (소스로 바로 확인할 때는 `.venv/bin/python app.py`)
  - 기본은 **보기 모드**(그리드 / 한 장 + 필름스트립, G로 그리드), **편집**(E)을 누르면 보정 패널이 있는 편집 화면
  - 그리드 **보기 옵션**(오른쪽 위 버튼·빈 곳 오른쪽 클릭·보기 메뉴): 맞춤 / 정사각형(꽉 채우기), 크기 4단계(⌘+ ⌘−),
    파일 이름 표시. 썸네일 배지: 주황 점 = 보정함, 초록 체크 = 내보냄, 핀 = 위치 있음, 왼쪽 아래 별 = 별점
  - **별점** 1~3: 키 1·2·3으로 매기고 0으로 지움 (그리드에서 여러 장 선택하면 모두에). 보정값 파일의 `rating`에 저장.
    **별점 필터**(오른쪽 위 ☆ 버튼·보기 메뉴): ★ 1개 이상 / 2개 이상 / 3개 / 별점 없는 사진만 보기.
    필터를 켠 채 내보내기의 '전체'는 필터에 맞는 사진만
  - 처음 화면의 최근 폴더 옆 ×는 최근 목록에서만 지운다 (폴더·사진은 그대로)
  - 한 장 보기·편집의 **화면 확대**(스크롤, ⌘+ ⌘− ⌘0, 트랙패드, 더블클릭 맞춤↔100%)는 보이는 크기만 바꾸고
    원본 대비 %로 표시한다. 보정값이 아니다
  - **설정**(⌘,): RAW 카메라 톤 기본값(`settings.json`의 `camera_match_default`, CLI도 따름), 편집 화면 썸네일 위치
    (왼쪽 목록 / 아래 필름스트립, 보기 메뉴에도 있음), 편집을 마칠 때 저장 여부 묻기
  - 편집 화면의 **보기** 버튼(E·Esc): 이번 편집에서 보정이 바뀌었으면 저장 / 저장 안 함(편집 전으로 되돌림, 별점·위치는
    그대로) / 취소를 묻는다. 슬라이더 값은 그동안에도 보정값 파일에 바로 저장되므로 Claude Code는 평소처럼 파일을 읽으면 된다
  - **프리셋 가져오기**(프리셋 옆 ↓ 버튼·파일 메뉴): `.yaml`이나 라이트룸 `.xmp`를 `presets/<이름>.yaml`로 넣는다
    (같은 이름이 있으면 사용자에게 덮어쓰기·이름 바꾸기를 묻는다)
  - **프리셋 삭제**(프리셋 옆 휴지통·편집 메뉴): 내가 만든·가져온 프리셋은 휴지통으로, 기본 프리셋 15종은 앱 목록에서만
    숨긴다. 지운 프리셋을 쓰던 사진은 경고와 함께 프리셋 없이 처리된다. Claude Code는 프리셋 파일을 직접 지우지 않는다
  - 사진 **오른쪽 클릭**: 크게 보기·편집, 별점, 위치(GPS) 추가·지우기, 설정 복사·붙여넣기, Finder에서 보기, 내보내기,
    휴지통으로 이동(⌘⌫). 여러 장을 선택하고 오른쪽 클릭하면 선택한 사진 모두가 대상
  - 폴더를 열면 **하위 폴더의 사진까지** 함께 연다 (보기 메뉴 '하위 폴더 포함'으로 끔). `export/`·숨김 폴더는 제외.
    이때 '폴더 전체'를 CLI로 처리하려면 `--recursive`를 붙인다
- 기획서: `ref/기획서 2.md` (기획서 1은 claude.ai Docs의 "Z6 RAW 보정 스크립트 기획서")
- 브랜드: `ref/brand-identity.md` (원본 `ref/LUMIQ_Brand_Identity_Final.pdf`). Q는 Quality(AI의 약자 아님),
  화면에서는 LUMIQ의 Q만 강조색 (`gui/theme.py`의 `wordmark()`)

## 앱과 함께 쓰기

- **보정값 파일**: 사진 바로 옆 `<사진 파일 이름>.lumiq.json` (예: `~/Photos/0901/DSC_1236.NEF` →
  `~/Photos/0901/DSC_1236.NEF.lumiq.json`). 보정값·별점·위치가 여기에 있다. 따로 모아 두는 폴더는 없다.
  `file` 항목은 필요 없다 (파일 이름이 곧 사진). 확장자까지 붙이므로 RAW+JPEG 쌍도 겹치지 않는다.
  값이 하나도 남지 않으면 앱이 파일을 지운다. 예전 `edits/*.json`이 남아 있으면 앱이 시작할 때 사진 옆으로 옮긴다.
- 앱과 Claude Code는 **같은 보정값 파일을 공유**한다. 앱에서 슬라이더를 움직이면 바로 저장되고,
  Claude Code가 파일을 고치거나 새로 만들면 앱이 자동으로 다시 불러와 화면에 반영한다.
- 사용자가 "앱에서 보정한 DSC_1236" 같은 말을 하면 그 사진 옆 `.lumiq.json`을 읽어 현재 값을 확인한 뒤 고친다.
- **"지금 보고 있는 사진", "이 사진"**은 프로젝트 루트의 `.app_state.json`을 읽어 찾는다:
  `current`(사진 경로), `current_edit_file`(보정값 파일 전체 경로, 아직 없을 수 있음), `current_preview`(지금 화면 그대로의 1024px 이미지,
  `previews/_app_current.jpg`), `selected`(앱에서 선택한 사진들). 화면을 봐야 하면 `current_preview`만 Read한다.
  앱에서 폴더를 닫으면(폴더 이름 옆 ×) `current`가 `null`이다 — 이때는 어떤 사진인지 사용자에게 묻는다.
- 앱 오른쪽의 **AI 어시스턴트** 패널도 Claude Code(`claude -p`)를 부른다. 이때는 시스템 프롬프트로 현재 사진·적용값이
  함께 전달되고, 허용 도구는 읽기·편집·쓰기와 CLI 실행뿐이다. 앱 번들에서는 CLI가 `./lumiq ...`
  (앱이 이 폴더에 만드는 번들 CLI 링크, `.venv/bin/python main.py`와 같음)다.
- 앱이 열려 있어도 `--preview`는 그대로 써도 된다. 다만 사용자가 앱 화면에서 보고 있다면
  json만 고치고 "앱에서 확인해 보세요"라고 해도 된다 (미리보기 생성·열람 생략 → 사용량 절약).
- AI 패널의 `claude -p`는 이 프로젝트 폴더에서 돌고, 앱이 연 사진 폴더를 `--add-dir`로 허용받아 보정값 파일을 고친다.

## JPG 보정

- JPG·HEIC·PNG·WebP·TIFF도 같은 항목으로 보정한다 (HEIC는 pillow-heif로 읽음). 이미 카메라가 톤을 입힌 사진이라 RAW 기본 커브와 렌즈 보정은 기본으로 꺼진다.
- **JPG의 색온도는 상대값**이다: `--info`의 `as_shot_temperature`가 약 6500K(= 현재 색)로 나오고,
  여기서 올리면 따뜻하게, 내리면 차갑게 바뀐다. 하이라이트 복원 여지는 RAW보다 훨씬 작다.
- 폴더를 처리할 때 같은 폴더에 같은 이름의 NEF가 있는 JPG(RAW+JPEG 촬영)는 건너뛴다. 포함하려면 `--with-jpeg`.

## 절대 규칙

1. **원본 사진(NEF·JPG 등)은 수정·이동·삭제하지 않는다.** 원본 폴더에 쓰는 것은 `export/` 하위 폴더,
   사진별 보정값 파일 `<사진 파일 이름>.lumiq.json`, 사진별 `.yaml`뿐.
   앱의 '휴지통으로 이동'은 사용자가 직접 하는 동작이다 (macOS 휴지통으로, 보정값 json·같은 이름의 .yaml·.xmp와
   숨겨진 RAW+JPEG 쌍의 JPG도 함께). Claude Code는 사용자가 부탁해도 사진을 지우지 말고 앱에서 하도록 안내한다.
2. **export 결과 JPEG를 지우거나 덮어쓰지 않는다.** (스크립트가 같은 이름이면 `_1`, `_2` 번호를 붙임)
3. **사진은 `previews/`의 1024px 미리보기만 Read로 본다.** NEF나 원본 크기 export 파일은 열지 않는다 (사용량 절약).
4. **한 번에 바꾸는 항목은 사용자가 요청한 것 위주.** 요청과 무관한 값을 함께 바꾸지 않는다.
5. 보정값은 사진 옆 `<사진 파일 이름>.lumiq.json`에만 쓴다. 스크립트 코드를 고쳐서 보정하지 않는다.
6. 미리보기를 볼 때는 바꾼 사진만 본다. 여러 장이면 꼭 필요한 것만 골라 본다.

## 작업 순서

1. `--info`로 사진 정보 확인
   ```
   .venv/bin/python main.py ~/Photos/0901 --info            # 폴더: 장당 한 줄 요약
   .venv/bin/python main.py ~/Photos/0901/DSC_1236.NEF --info  # 한 장: 전체 항목
   ```
2. 사진 옆 `<사진 파일 이름>.lumiq.json` 작성 (예: `~/Photos/0901/DSC_1236.NEF.lumiq.json`, 아래 형식,
   이미 있으면 그 파일을 고침)
3. 미리보기 생성 (사진 옆 보정값 파일이 자동으로 적용됨): `.venv/bin/python main.py ~/Photos/0901/DSC_1236.NEF --preview`
   - 폴더 전체: `.venv/bin/python main.py ~/Photos/0901 --preview`
   - 일부만: `--only DSC_1236,DSC_1240`
4. `previews/DSC_1236.jpg`를 Read로 확인 → 사용자에게 무엇을 바꿨는지 짧게 보고
5. 사용자 피드백에 따라 2~4 반복
6. 만족하면 같은 값으로 최종 export
   ```
   .venv/bin/python main.py ~/Photos/0901 --size 2048
   .venv/bin/python main.py ~/Photos/0901/DSC_1236.NEF            # 원본 크기
   ```
   출력: 기본 `<원본 폴더>/export/DSC_1236_edit.jpg`(하위 폴더 사진은 그 폴더의 `export/`), `--out 폴더`로 변경
   (`--recursive`와 `--out`을 같이 쓰면 그 안에 하위 폴더 구조를 유지)

실행 로그의 `적용값:` 줄에 실제 적용된 색온도·노출·톤 값이 나온다. 재조정할 때 이 값을 기준으로 삼는다.

## 명령과 옵션

| 옵션 | 역할 |
| --- | --- |
| `-r`, `--recursive` | 폴더 입력일 때 하위 폴더의 사진까지 (`export/`·숨김 폴더 제외) |
| `--info` | EXIF, ISO, 화이트밸런스, 히스토그램 요약, 얼굴 위치, 자동 수평 각도, 자동 보정 제안(`auto_suggestion`)을 JSON으로 출력. 여러 장이면 요약, `--verbose`로 전체 |
| `--preview` | 긴 변 1024px 미리보기를 `previews/<파일명>.jpg`에 저장 (매번 덮어씀) |
| `--params 파일\|폴더` | 생략하면 사진 옆 `.lumiq.json`을 쓴다. 다른 보정값 JSON/YAML을 쓸 때만 지정 (폴더면 사진마다 `<사진 파일 이름>.lumiq.json`) |
| `--preset 이름` | `presets/<이름>.yaml` (기본 `portrait`·`snap` + 계절·장소 13종, 아래 '프리셋' 참고) |
| `--xmp 파일` | 라이트룸 .xmp 프리셋 |
| `--auto` | 원클릭 자동 보정 (노출·WB·톤, 얼굴 노출 우선) |
| `--ai-denoise` | AI 노이즈 제거 (SCUNet, MPS). 느림: 원본 크기 약 40초/장, 미리보기 약 5초 |
| `--size N` | 긴 변 N px로 축소 후 출력용 샤프닝 (기본 원본 크기) |
| `--quality N` | JPEG 품질 (기본 92) |
| `--out 폴더` | export 폴더 |
| `--save-preset 이름` | 설정을 `presets/<이름>.yaml`로 저장 (색감·톤만, 크롭·노출·WB 같은 사진별 값은 제외) |
| `--set 키=값` | 임의 항목 지정, 예: `--set skin.smooth=20` |
| `--crop`, `--rotate`, `--rotate90 cw\|ccw\|180`, `--flip h\|v`, `--no-auto-level`, `--no-lens` | 기하 |
| `--exposure`, `--wb`(색온도), `--tint`, `--contrast` 등 | 단일 보정값 |
| `--device cpu` | GPU(MPS) 대신 CPU |

## 보정값 파일(.lumiq.json) 형식

항목 이름은 라이트룸 방식 프리셋과 같다. 쓰지 않는 항목은 생략한다 (생략 = 프리셋 값 또는 0).
아래는 `~/Photos/0901/DSC_1236.NEF.lumiq.json`의 예:

```json
{
  "preset": "portrait",
  "auto": true,
  "exposure": 0.4,
  "shadows": 20,
  "temperature": 5400,
  "skin": {"brightness": 10, "smooth": 15},
  "lut": {"file": "luts/film.cube", "strength": 50},
  "crop": "4:5",
  "rotate": 0.8
}
```

### 항목별 값 범위

| 항목 | 범위 | 설명 |
| --- | --- | --- |
| `temperature` | 2000~50000 (K) | 생략 시 촬영 시 값. 높을수록 따뜻하게. `--info`의 `as_shot_temperature`가 기준 |
| `tint` | −150~+150 | +마젠타, −초록 |
| `exposure` | −5~+5 (EV) | |
| `contrast`, `highlights`, `shadows`, `whites`, `blacks` | −100~+100 | |
| `texture`, `clarity`, `dehaze` | −100~+100 | |
| `vibrance`, `saturation` | −100~+100 | 바이브런스는 피부톤을 덜 건드림 |
| `tone_curve` (+ `_red`, `_green`, `_blue`) | `[[x,y], ...]` 0~255 | 예: 바랜 블랙 `[[0,20],[64,58],[192,200],[255,245]]` |
| `hsl.<색>.hue/saturation/luminance` | −100~+100 | 색: red, orange, yellow, green, aqua, blue, purple, magenta |
| `color_grading.<영역>.hue` | 0~360 | 영역: shadows, midtones, highlights, global |
| `color_grading.<영역>.saturation` | 0~100 | |
| `color_grading.<영역>.luminance` | −100~+100 | |
| `color_grading.blending` / `balance` | 0~100 / −100~+100 | |
| `skin.brightness` | −100~+100 | 얼굴 피부만 (눈·입술 제외) |
| `skin.smooth` | 0~100 | 피부 매끈하게. 15~30이 자연스러움, 50 이상은 티 남 |
| `skin.saturation`, `skin.warmth` | −100~+100 | 피부 채도, 따뜻함 |
| `lut.file` / `lut.strength` | `luts/*.cube` / 0~100 | |
| `sharpening.amount/radius/detail/masking` | 0~150 / 0.5~3 / 0~100 / 0~100 | |
| `noise_reduction.luminance/color` | 0~100 | 일반 노이즈 감소 (AI 아님) |
| `vignette.amount/midpoint/feather` | −100~+100 / 0~100 / 0~100 | −가 어둡게 |
| `grain.amount/size/roughness` | 0~100 | |
| `ai_denoise` | `true` 또는 `{"strength": 0~100}` | ISO 6400 이상이면 켜기 권장 |
| `auto` | `true/false` | 자동 보정 |
| `auto_brightness` | −100~+100 | 자동 보정의 밝기 선호 (앱의 '자동 밝기'). 노출만이 아니라 목표 밝기·섀도·하이라이트·흰색·검정·대비를 함께 다시 계산. `auto: true`일 때만 적용 |
| `crop` | `"3:2"`, `"4:5"`, `"1:1"`, `"16:9"`, `"original"` | |
| `crop_orientation` | `auto`(기본, 사진 방향에 맞춤) / `portrait` / `landscape` / `as_is` | 가로 사진을 세로 4:5로 자르려면 `portrait` |
| `crop_center` | `[x, y]` 0~1 | 크롭 위치 (기본 가운데). 얼굴 쪽으로 옮길 때 `--info`의 얼굴 bbox 참고 |
| `crop_rect` | `[x, y, 가로, 세로]` 0~1 | 앱의 화면 자르기(R)가 쓰는 자유 크롭 영역 (90° 회전·반전 후, `rotate`로 기울인 화면 기준). 있으면 `crop`·`crop_center`보다 우선. 비율만 바꾸려면 `crop_rect`를 지우고 `crop`을 쓴다 |
| `rotate` | −45~+45 (°) | +가 시계 방향. 자동 수평값에 더해짐 |
| `rotate90` / `flip` | `cw`,`ccw`,`180` / `h`,`v` | |
| `auto_level` | `true`(기본)/`false` | 직선이 부족한 사진은 자동으로 회전 안 함. 앱에서 화면으로 각도를 맞추면 `false`로 고정됨 |
| `lens` | `true`(기본)/`false` | lensfun 렌즈 보정, 프로필 없으면 건너뜀 |
| `camera_match` | `true/false` | RAW만. RAW 안의 카메라 JPEG(니콘 액티브 D-라이팅·픽처 컨트롤이 들어간 밝기·채도)에 맞춰 기본 톤을 잡는다. 디코딩 직후에 적용되어 노출·자동 보정·슬라이더는 그 위에서 동작. 생략하면 `settings.json`의 `camera_match_default`(없으면 끔). 앱의 '카메라 톤' |
| `rating` | 1~3 | 별점 (앱의 1·2·3 키, 0 키는 이 항목을 지움). 보정값이 아니라 렌더·내보내기에 영향 없고, 썸네일 '보정함' 표시·설정 복사·프리셋 저장에서 빠진다. "별점 3개인 사진"은 사진 옆 `.lumiq.json`의 `rating`으로 찾는다 |
| `gps` | `{"lat": 37.5665, "lon": 126.978, "name": "서울시청"}` | 위치 추가 (위도 −90~90, 경도 −180~180, `name`은 표시용·선택). 원본은 그대로 두고 **내보낸 JPEG**에만 기록 (원래 GPS가 있으면 이 값으로 바뀜). 보정값이 아니라 썸네일 '보정함' 표시·설정 복사·프리셋 저장에서 빠진다. 앱의 오른쪽 클릭 '위치(GPS) 추가'가 쓰는 항목 |

범위를 벗어난 값은 스크립트가 잘라내고 경고한다.

### 설정 우선순위

뒤의 값이 앞의 값을 덮어쓴다: **자동 보정 < 프리셋/xmp < 사진별 yaml(NEF 옆 `DSC_1236.yaml`) < 보정값 파일(`.lumiq.json`) < CLI 옵션**

- 단, `auto`가 켜져 있으면 프리셋의 `exposure`, `highlights`, `shadows`, `whites`, `blacks`는 자동값에 **더해진다**.
- 보정값 파일의 값은 **최종값**이다. 자동값 기준으로 조금 바꾸려면 `적용값:` 로그나 `--info`의 `auto_suggestion`에 더한 값을 쓴다.
  (예: 자동 노출 1.2에서 "조금 더 밝게" → `"exposure": 1.5`)

## 요청 → 보정값 가이드

| 사용자 표현 | 우선 바꿀 항목 (1회 변화량) |
| --- | --- |
| RAW가 카메라 JPEG·썸네일보다 어둡다 (액티브 D-라이팅) | `camera_match: true` 먼저, 그다음 필요하면 노출 |
| 어둡다 / 밝게 | `exposure` ±0.3~0.5, 그늘만 어두우면 `shadows` +15~25. 자동 보정이 켜져 있으면 `auto_brightness` ±30~50 |
| 하늘·하이라이트 날아감 | `highlights` −20~−40, 필요하면 `exposure` −0.2 |
| 피부가 칙칙함 | `skin.brightness` +10, `skin.saturation` −5~+5, 전체가 탁하면 `vibrance` +10 |
| 피부 매끈하게 | `skin.smooth` +10~15 |
| 화사하게 | `exposure` +0.2, `shadows` +10, `contrast` −5~−10, `skin.brightness` +5~10 |
| 따뜻하게 / 차갑게 | `temperature` ±300~500K |
| 필름 느낌 | `lut` (film.cube) 강도 +20, `grain.amount` 15~25, 바랜 블랙 `tone_curve` |
| 선명하게 | `texture` +10, `clarity` +10, `sharpening.amount` +15 |
| 뿌옇다 | `dehaze` +10~20 |
| 노이즈 많다 | `ai_denoise: true` (또는 `noise_reduction.luminance` +20) |
| 색이 과하다 | `saturation` −10 또는 해당 색 `hsl.<색>.saturation` −15 |
| 기울었다 | `rotate` ±0.5~2 |
| 인스타용 | `crop: "4:5"`, `crop_orientation: "portrait"` |

보고는 짧게: "노출 +0.4, 섀도 +20, 피부 밝기 +10으로 바꿨어요. 미리보기 확인해 보세요."

## 프리셋

- 위치: `presets/<이름>.yaml`, 이름은 영문 소문자·숫자·밑줄 (`my_film`, `cafe_warm`)
- 저장: `.venv/bin/python main.py ~/Photos/0901/DSC_1236.NEF --save-preset my_film`
  (그 사진의 프리셋+보정값 파일 값을 합쳐 저장. 노출·WB·크롭 같은 사진별 값은 빠짐)
- 여러 사진에 적용: 각 사진 옆 `.lumiq.json`의 `"preset"`을 바꾸거나 `--preset my_film`
- 기존 프리셋 파일을 덮어쓰기 전에 사용자에게 확인한다.
- 파일 머리의 `label`(앱에 보일 한글 이름)·`description`은 설명용이라 보정값이 아니다.
  이름이 `spring_`·`summer_`·`autumn_`·`winter_`로 시작하면 앱 목록에서 계절별로 묶인다.

### 계절·장소 프리셋 (장면에 맞춰 고른다, 자동 보정과 함께 쓰면 좋음)

| 장면 | 프리셋 | 느낌 |
| --- | --- | --- |
| 봄 벚꽃·꽃길 | `spring_cherry` | 화사한 분홍, 밝은 하늘, 파스텔 (LUT 파스텔 블룸) |
| 봄 공원·들판·신록 | `spring_park` | 맑은 연두, 상쾌함 |
| 봄 카페·창가 실내 | `spring_cafe` | 따뜻한 크림 톤, 살짝 바랜 필름 |
| 여름 바다·해변·수영장 | `summer_beach` | 투명한 바다색, 진한 하늘 (LUT 여름 아쿠아) |
| 여름 도심 한낮 | `summer_city` | 쨍하고 시원한 대비 |
| 여름 계곡·숲 | `summer_valley` | 짙고 차분한 초록, 시원한 물빛 |
| 야경·네온 도시 | `summer_night` | 깊은 검정, 청록 그림자, 네온 (LUT 네온 나이트) |
| 가을 단풍 | `autumn_foliage` | 붉고 노란 단풍 강조, 초록은 올리브 (LUT 가을 앰버) |
| 가을 억새·노을·역광 | `autumn_golden` | 금빛 하이라이트 (LUT 골든아워) |
| 가을 골목·거리 스냅 | `autumn_street` | 바랜 블랙 + 그레인 필름 |
| 겨울 설경 | `winter_snow` | 하얗고 깨끗한 눈 (노출 +0.3, LUT 맑은 설경) |
| 겨울 크리스마스 거리·조명 | `winter_lights` | 따뜻한 전구빛 + 차가운 밤 |
| 겨울 실내·카페 | `winter_cozy` | 아늑한 웜 톤 |

### LUT (`luts/`, 강도 30~60이 자연스러움)

`film`(필름 기본), `warm_film`(따뜻한 필름), `cool_film`(시원한 필름), `teal_orange`(시네마 틸·오렌지),
`matte_fade`(매트 페이드), `golden_hour`(골든아워), `pastel_bloom`(파스텔 블룸), `neon_night`(네온 나이트),
`snow_clean`(맑은 설경), `autumn_amber`(가을 앰버), `summer_aqua`(여름 아쿠아), `mono_film`(흑백 필름).
`film`을 뺀 나머지는 `tools/make_luts.py`가 만든다 (색감을 고치려면 그 함수를 고치고 다시 실행).

## 폴더 구조

```
main.py              CLI 진입점
app.py               데스크톱 앱 진입점 (PySide6)
tools/make_luts.py   luts/*.cube 생성 (film.cube 제외)
tools/build_app.py   독립 앱 번들을 /Applications에 설치 (코드·패키지를 고쳤거나 프로젝트 폴더를 옮기면 다시 실행)
gui/                 앱 화면: window, widgets(슬라이더·크롭·비교선), engine(단계별 캐시 렌더), workers,
                     assistant(AI 패널 → claude -p), theme(색·아이콘), icon
.app_state.json      앱이 지금 보는 사진·선택 (Claude Code용, 앱이 자동으로 씀)
lumiq                앱 번들 안 CLI로 가는 링크 (AI 패널이 만듦, = main.py)
pipeline/            decode, lens, geometry, tone, skin, lut, detail, export, params, runner, files
ai/                  auto(원클릭), denoise(SCUNet), face(MediaPipe)
presets/             *.yaml, xmp_reader.py
luts/                *.cube
models/              scunet_color_real_psnr.pth, face_landmarker.task
previews/            1024px 미리보기 (Claude Code가 보는 곳)
settings.json        보정 결과에 영향을 주는 앱 설정 (camera_match_default). 앱의 설정(⌘,)이 씀
pipeline/camera.py   카메라 톤 맞추기 (내장 카메라 JPEG에 밝기·채도 맞춤)

(사진 폴더)/DSC_1236.NEF.lumiq.json   그 사진의 보정값 (사진 옆, 사진마다 하나)
```

## 참고

- 결과는 라이트룸과 비슷하지만 같지 않은 근사치다. xmp의 프로파일(내장 LUT)과 마스크 부분 보정은 무시된다.
- 피부 보정·자동 보정의 얼굴 검출은 MediaPipe. 얼굴이 없으면 피부 보정은 건너뛴다.
- 미리보기는 절반 크기로 디코딩해 빠르게(약 0.5초) 만든다. 최종 결과와 색·톤은 같고 디테일(샤프닝·노이즈)만 조금 다르다.
- 앱 로그: `~/Library/Logs/LUMIQ Studio.log`
