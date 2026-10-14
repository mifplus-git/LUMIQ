# LUMIQ Studio

[한국어](README.md) · **English**

> **Understand the Light. Perfect the Image.**  
> 빛을 이해하고, 사진을 완성하다.

LUMIQ is an intelligent photo editing brand that uses AI to analyze the light, color, exposure and detail of a photo
and raise its quality and finish. It lets anyone finish a photo quickly and easily, while keeping the freedom to refine it
by hand to their own taste and style.

- **LUMI**: the beauty of light and image (brightness, color, mood)
- **Q**: Quality, the quality and finish of a photo

Full brand overview (in Korean): [LUMIQ Brand Identity](ref/brand-identity.md)

**LUMIQ Studio** is a macOS photo editor that develops Nikon Z6 RAW (NEF) files, as well as JPG, HEIC, PNG, WebP and TIFF, and exports them as JPEG.
It comes as a desktop app and a command-line tool (CLI).

All image processing runs locally on your Mac. Paired with [Claude Code](https://claude.com/claude-code), Claude can analyze
a photo, choose the adjustments, and refine them through conversation. The code itself contains no API keys and makes no LLM calls.

> The UI, CLI messages and [CLAUDE.md](CLAUDE.md) are written in Korean.

## Features

- **Lightroom-style adjustments**: exposure, white balance, contrast / highlights / shadows / whites / blacks,
  texture / clarity / dehaze, vibrance / saturation, HSL, color grading, tone curve, sharpening, noise reduction,
  vignette, grain
- **One-click auto**: sets exposure, white balance and tone, prioritizing face exposure when a face is found
- **Camera match**: matches brightness and saturation to the camera JPEG embedded in the RAW
  (Nikon Active D-Lighting and Picture Control)
- **Skin retouching**: brightness, smoothing, saturation and warmth on facial skin only
  (MediaPipe face detection, eyes and lips excluded)
- **AI denoise**: SCUNet on the Apple Silicon GPU (MPS)
- **15 presets**: portrait, snap, and 13 season/scene presets (cherry blossoms, beach, night city, autumn foliage,
  snow, …). Imports Lightroom `.xmp` presets
- **12 LUTs**: film, cinematic teal & orange, golden hour, pastel bloom, mono film, and more
- **Geometry**: lens correction (lensfun), auto leveling, crop (3:2, 4:5, 1:1, 16:9, free), rotate and flip
- **Organizing**: star ratings, rating filter, add a location (GPS), original EXIF preserved
- **Originals are never modified.** Adjustments are stored next to each photo in `<photo file name>.lumiq.json`

## Requirements

- macOS 13 or later, Apple Silicon (arm64)
- Python 3.12 (arm64)
- Homebrew: `exiftool` (EXIF and location writing), `lensfun` (lens correction)
- Optional: Claude Code (the app's AI assistant and conversational editing)

## Installation

```bash
git clone https://github.com/mifplus-git/LUMIQ.git
cd LUMIQ
brew install python@3.12 exiftool lensfun
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Model weights are not included in the repository because of their size. Download them into `models/`:

```bash
mkdir -p models
curl -L -o models/scunet_color_real_psnr.pth \
  https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth
curl -L -o models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

Everything still runs without the models, but AI denoise and face detection fall back to simpler OpenCV methods.

## App

```bash
.venv/bin/python app.py              # opens the last folder
.venv/bin/python app.py ~/Photos/0901
```

To install a standalone app, run the command below. It builds `/Applications/LUMIQ Studio.app` with Python, packages,
code, models and exiftool bundled inside, so it runs without this folder or Homebrew.
Run it again after changing the code to update the app.

```bash
.venv/bin/python tools/build_app.py
```

The app opens in **view mode** (grid / single photo). Press **E** to switch to the edit screen with the adjustment panel.

| Key | Action |
| --- | --- |
| ⌘O | Open a folder (or drag folders and photos onto the window) |
| G / E | Grid view / Edit · Done |
| ← → | Previous · next photo |
| 1 2 3 / 0 | Set / clear star rating |
| R | Crop and rotate |
| \\ | Before / after comparison |
| ⇧⌘C / ⇧⌘V | Copy settings / paste to selected photos |
| ⌘K | AI assistant |
| ⌘E | Export |
| ⌘? | Help and all shortcuts |

## CLI

```bash
# Photo info (EXIF, white balance, histogram, face positions, auto-adjust suggestion)
.venv/bin/python main.py ~/Photos/0901 --info

# 1024px preview → previews/
.venv/bin/python main.py ~/Photos/0901/DSC_1236.NEF --preview

# Export
.venv/bin/python main.py ~/Photos/0901 --preset portrait --size 2048
.venv/bin/python main.py DSC_1234.NEF --exposure +0.3 --wb 5200
.venv/bin/python main.py ~/Photos/0901 --xmp ~/presets/film.xmp --auto --ai-denoise
```

Output goes to `<source folder>/export/<file name>_edit.jpg` (change it with `--out`).
Existing files are never overwritten; `_1`, `_2` is appended instead. Run `--help` for all options.

## Adjustment files

Each photo gets a `<photo file name>.lumiq.json` next to it (e.g. `DSC_1236.NEF` → `DSC_1236.NEF.lumiq.json`).
The app, the CLI and Claude Code all share this file, so a change made in one shows up in the others right away.

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

Precedence (later wins): auto adjust < preset/xmp < per-photo yaml < `.lumiq.json` < CLI options.
Value ranges for every field are listed in [CLAUDE.md](CLAUDE.md).

## Using with Claude Code

- Open Claude Code in this folder and it follows the rules in [CLAUDE.md](CLAUDE.md):
  check the photo with `--info` → write `.lumiq.json` → render a `--preview` → review and refine → export.
  For example: "DSC_1236 is a bit dark and the skin looks dull", "Apply the portrait preset to the 0901 folder".
- The app's **AI assistant** (⌘K) runs the `claude` installed on your Mac as `claude -p`.
  - It uses whatever Claude Code login already exists on that Mac, so no API key is needed, and no account
    information is stored in the app or the repository.
  - The only tools it may use are reading, editing and writing files, and running the LUMIQ CLI.

## Project layout

```
main.py              CLI
app.py               Desktop app (PySide6)
gui/                 App UI (window, widgets, render engine, AI assistant panel)
pipeline/            Decode, lens, geometry, tone, skin, LUT, detail, export
ai/                  Auto adjust, AI denoise (SCUNet), face detection (MediaPipe)
presets/             Presets (*.yaml), Lightroom xmp reader
luts/                LUTs (*.cube)
models/              Model weights (download separately)
tools/               build_app.py (app bundle), make_luts.py (LUT generator)
CLAUDE.md            Working rules for Claude Code
```

## Notes

- Results are close to Lightroom but not identical. Profiles embedded in xmp files (built-in LUTs) and masked local
  adjustments are not applied.
- Model weights are subject to their own licenses: SCUNet ([cszn/KAIR](https://github.com/cszn/KAIR)),
  Face Landmarker ([Google MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)).
