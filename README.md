# LUMIQ Studio

**한국어** · [English](README.en.md)

> **빛을 이해하고, 사진을 완성하다.**  
> Understand the Light. Perfect the Image.

LUMIQ는 AI로 사진의 빛과 색상, 노출과 디테일을 분석해 사진의 품질과 완성도를 높이는 지능형 사진 편집 브랜드입니다.
누구나 빠르고 간편하게 사진을 완성할 수 있게 하면서도, 자신의 취향과 스타일대로 직접 다듬는 편집의 자유를 함께 지향합니다.

- **LUMI**: 빛과 이미지의 아름다움 (밝기, 색감, 분위기)
- **Q**: Quality, 사진의 품질과 완성도

브랜드 소개 전체: [LUMIQ 브랜드 아이덴티티](ref/brand-identity.md)

**LUMIQ Studio**는 니콘 Z6 RAW(NEF)와 JPG·HEIC·PNG·WebP·TIFF 사진을 보정해 JPEG로 내보내는 사진 보정 도구입니다.
데스크톱 앱과 명령줄(CLI) 두 가지로 쓸 수 있고, Apple Silicon(M 칩) Mac과 Windows에서 실행됩니다.

보정 연산은 모두 내 컴퓨터에서 로컬로 처리합니다. [Claude Code](https://claude.com/claude-code)와 함께 쓰면 Claude가 사진을 분석해
보정값을 정하고, 대화로 다시 조정할 수 있습니다. 코드에는 API 키나 LLM 호출이 들어 있지 않습니다.

## 주요 기능

- **라이트룸 방식 보정 항목**: 노출, 화이트밸런스, 대비·하이라이트·섀도·흰색·검정, 텍스처·명료도·디헤이즈,
  바이브런스·채도, HSL, 컬러 그레이딩, 톤 커브, 샤프닝, 노이즈 감소, 비네트, 그레인
- **원클릭 자동 보정**: 노출·화이트밸런스·톤을 맞추고, 얼굴이 있으면 얼굴 노출을 우선합니다
- **카메라 톤 맞추기**: RAW 안의 카메라 JPEG(니콘 액티브 D-라이팅·픽처 컨트롤)에 밝기·채도를 맞춥니다
- **피부 보정**: 얼굴 피부만 밝기·매끈함·채도·따뜻함 조절 (MediaPipe 얼굴 검출, 눈·입술 제외)
- **AI 노이즈 제거**: SCUNet (Mac은 GPU(MPS), Windows는 CPU)
- **프리셋 15종**: 인물·스냅과 계절·장소 13종(벚꽃, 바다, 야경, 단풍, 설경 등). 라이트룸 `.xmp` 프리셋 가져오기
- **LUT 12종**: 필름, 시네마 틸·오렌지, 골든아워, 파스텔 블룸, 흑백 필름 등
- **기하 보정**: 렌즈 보정(lensfun), 자동 수평, 크롭(3:2·4:5·1:1·16:9·자유), 회전·반전
- **정리**: 별점, 별점 필터, 위치(GPS) 추가, 원본 EXIF 유지
- **원본은 절대 바꾸지 않습니다.** 보정값은 사진 옆 `<사진 파일 이름>.lumiq.json`에 저장됩니다

## 지원 환경

| | Mac (Apple Silicon, M 칩) | Windows 10·11 (64비트) |
| --- | --- | --- |
| 앱·CLI | ✅ | ✅ |
| 독립 앱 만들기 | ✅ `LUMIQ Studio.app` | — (소스에서 실행, 바로가기로 띄움) |
| AI 노이즈 제거 | GPU (MPS) | CPU (느림) |
| 파일 위치 보기 | Finder | 파일 탐색기 |

- Python 3.12와 exiftool이 필요합니다. exiftool이 없어도 실행은 되지만 EXIF·위치 기록과 렌즈 보정이 빠집니다.
- 선택: [Claude Code](https://claude.com/claude-code) (앱의 AI 어시스턴트, 대화형 보정)
- Intel Mac과 Linux는 지원하지 않습니다 (Intel Mac은 PyTorch가 새 버전을 내지 않음).
- 화면 글자는 한국어입니다. 단축키는 OS에 맞게 바뀝니다 (Mac의 ⌘ = Windows의 Ctrl).

## OS별 설치

### Mac (Apple Silicon, M 칩)

```bash
brew install python@3.12 exiftool
git clone https://github.com/mifplus-git/LUMIQ.git
cd LUMIQ
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

**독립 앱 만들기**: Python·패키지·코드·모델·exiftool을 모두 담은 `LUMIQ Studio.app`을 만듭니다.
이 폴더나 Homebrew 없이도 실행되고, 코드를 고친 뒤에는 다시 만들어야 앱에 반영됩니다.
Xcode 명령줄 도구가 필요합니다 (`xcode-select --install`).

```bash
.venv/bin/python tools/build_app.py                 # /Applications에 설치
.venv/bin/python tools/build_app.py ~/Applications  # 다른 폴더에
```

### Windows

PowerShell에서 실행합니다.

```powershell
winget install Python.Python.3.12
winget install OliverBetz.ExifTool
# 설치한 뒤 PowerShell을 새로 열어야 PATH가 반영됩니다
git clone https://github.com/mifplus-git/LUMIQ.git
cd LUMIQ
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

- 콘솔 창 없이 띄우려면 `.venv\Scripts\pythonw app.py`를 씁니다.
- 바탕 화면 바로가기: 대상은 `<LUMIQ 폴더>\.venv\Scripts\pythonw.exe app.py`, 시작 위치는 `<LUMIQ 폴더>`로 지정합니다.
- 아래 예시의 `.venv/bin/python`은 Windows에서 `.venv\Scripts\python`입니다.

### 모델 가중치 (Mac·Windows 공통)

모델 가중치는 용량 때문에 저장소에 들어 있지 않습니다. `models/`에 내려받으세요.

```bash
# Mac (터미널)
mkdir -p models
curl -L -o models/scunet_color_real_psnr.pth \
  https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth
curl -L -o models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

```powershell
# Windows (PowerShell)
mkdir models
curl.exe -L -o models/scunet_color_real_psnr.pth https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth
curl.exe -L -o models/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

모델이 없어도 실행은 됩니다. 다만 AI 노이즈 제거와 얼굴 검출이 더 단순한 OpenCV 방식으로 대체됩니다.

### 설치 확인 (Mac·Windows 공통)

```bash
.venv/bin/python tools/smoke_test.py      # Windows: .venv\Scripts\python tools\smoke_test.py
```

임시 폴더에 테스트 사진을 만들어 패키지, CLI(정보·미리보기·자동 보정·내보내기), 앱 창(화면에 띄우지 않음)을 차례로 확인합니다.
모두 ✓이면 설치가 끝난 것입니다. GitHub에서도 Actions의 **설치 확인**이 Windows에서 이 순서대로 설치해 같은 확인을 합니다.

## 앱

```bash
.venv/bin/python app.py              # 마지막에 연 폴더로 시작
.venv/bin/python app.py ~/Photos/0901
```

기본은 **보기 모드**(그리드 / 한 장)이고, **E**를 누르면 보정 패널이 있는 편집 화면으로 바뀝니다.

| 동작 | Mac | Windows |
| --- | --- | --- |
| 폴더 열기 (폴더·사진을 창에 끌어다 놓아도 됨) | ⌘O | Ctrl+O |
| 그리드 보기 / 편집 · 완료 | G / E | G / E |
| 이전 · 다음 사진 | ← → | ← → |
| 별점 매기기 / 지우기 | 1 2 3 / 0 | 1 2 3 / 0 |
| 자르기·회전 | R | R |
| 보정 전·후 비교 | \\ | \\ |
| 설정 복사 / 선택한 사진에 붙여넣기 | ⇧⌘C / ⇧⌘V | Ctrl+Shift+C / Ctrl+Shift+V |
| AI 어시스턴트 | ⌘K | Ctrl+K |
| 내보내기 | ⌘E | Ctrl+E |
| 휴지통으로 이동 | ⌘⌫ | Delete |
| 설정 | ⌘, | Ctrl+, |
| 사용법 · 전체 단축키 | ⌘? | F1 |

## CLI

```bash
# 사진 정보 (EXIF, 화이트밸런스, 히스토그램, 얼굴 위치, 자동 보정 제안)
.venv/bin/python main.py ~/Photos/0901 --info

# 1024px 미리보기 → previews/
.venv/bin/python main.py ~/Photos/0901/DSC_1236.NEF --preview

# 내보내기
.venv/bin/python main.py ~/Photos/0901 --preset portrait --size 2048
.venv/bin/python main.py DSC_1234.NEF --exposure +0.3 --wb 5200
.venv/bin/python main.py ~/Photos/0901 --xmp ~/presets/film.xmp --auto --ai-denoise
```

결과는 `<원본 폴더>/export/<파일 이름>_edit.jpg`에 저장됩니다 (`--out`으로 바꿀 수 있음).
같은 이름이 있으면 덮어쓰지 않고 `_1`, `_2`를 붙입니다. 전체 옵션은 `--help`로 볼 수 있습니다.

## 보정값 파일

사진마다 옆에 `<사진 파일 이름>.lumiq.json`이 생깁니다 (예: `DSC_1236.NEF` → `DSC_1236.NEF.lumiq.json`).
앱과 CLI, Claude Code가 같은 파일을 함께 쓰므로, 어느 쪽에서 고쳐도 다른 쪽에 바로 반영됩니다.

```json
{
  "preset": "portrait",
  "auto": true,
  "exposure": 0.4,
  "shadows": 20,
  "temperature": 5400,
  "skin": {"brightness": 10, "smooth": 15},
  "lut": {"file": "luts/film.cube", "strength": 50},
  "crop": "4:5"
}
```

설정 우선순위 (뒤가 앞을 덮어씀): 자동 보정 < 프리셋/xmp < 사진별 yaml < `.lumiq.json` < CLI 옵션.
항목별 값 범위는 [CLAUDE.md](CLAUDE.md)에 정리되어 있습니다.

## Claude Code와 함께 쓰기

- 이 폴더에서 Claude Code를 열면 [CLAUDE.md](CLAUDE.md)의 규칙에 따라 작업합니다.
  `--info`로 사진 확인 → `.lumiq.json` 작성 → `--preview`로 미리보기 → 확인 후 재조정 → 내보내기 순서입니다.
  예: "DSC_1236 좀 어둡고 피부가 칙칙해", "0901 폴더 인물 프리셋으로 정리해줘"
- 앱의 **AI 어시스턴트**(⌘K · Ctrl+K)는 컴퓨터에 설치된 `claude`를 `claude -p`로 실행합니다.
  - 각자 컴퓨터에 로그인된 Claude Code를 그대로 쓰므로 API 키가 필요 없고, 계정 정보는 앱이나 저장소에 저장되지 않습니다.
  - 허용하는 도구는 파일 읽기·편집·쓰기와 LUMIQ CLI 실행뿐입니다.

## 폴더 구조

```
main.py              CLI
app.py               데스크톱 앱 (PySide6)
gui/                 앱 화면 (창, 위젯, 렌더 엔진, AI 어시스턴트 패널)
pipeline/            디코딩, 렌즈, 기하, 톤, 피부, LUT, 디테일, 내보내기
ai/                  자동 보정, AI 노이즈 제거(SCUNet), 얼굴 검출(MediaPipe)
presets/             프리셋 (*.yaml), 라이트룸 xmp 읽기
luts/                LUT (*.cube)
models/              모델 가중치 (직접 내려받음)
tools/               build_app.py (macOS 앱 번들), make_luts.py (LUT 생성)
CLAUDE.md            Claude Code 작업 규칙
```

## 참고

- 결과는 라이트룸과 비슷하지만 같지는 않은 근사치입니다. xmp의 프로파일(내장 LUT)과 마스크 부분 보정은 적용되지 않습니다.
- 모델 가중치는 각 배포처의 라이선스를 따릅니다: SCUNet ([cszn/KAIR](https://github.com/cszn/KAIR)),
  Face Landmarker ([Google MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)).

## 라이선스

LUMIQ는 [GNU General Public License v3.0](LICENSE)(GPL-3.0)으로 배포됩니다.
외부 라이브러리와 모델 가중치는 각자의 라이선스를 따릅니다.
