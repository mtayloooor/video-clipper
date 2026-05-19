# ✂ video-clipper

A fast, free desktop app that cuts multiple clips from any video — no watermark, no internet, no subscription.

Built with Python + Tkinter, powered by FFmpeg under the hood.

![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python)
![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green?style=flat-square&logo=ffmpeg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-purple?style=flat-square)

---

## What It Does

You give it one video. You pick how many clips and how long each should be. It evenly spreads them across the full video and exports them — re-encoded to your chosen aspect ratio and quality.

Perfect for repurposing long videos into short-form content for TikTok, Reels, Shorts, or Instagram.

---

## Features

- **Multiple aspect ratios** — 9:16, 1:1, 16:9, 4:5
- **4 resize modes** — Black Bars, Blur Background, Center Crop, Stretch
- **Quality presets** — Fast (720p) and Good (1080p)
- **Live progress log** — see FFmpeg output in real time
- **Stop anytime** — cancel mid-batch cleanly
- **No watermark** — output is clean MP4
- **Fully offline** — no API, no account, no internet needed

---

## Preview

```
✂ Video Clipper — Fast & Free
─────────────────────────────────────────
 📁 Browse Video        [myvideo.mp4]

 Number of Clips: 6     Seconds Per Clip: 10     Total: 6 × 10s = 60s

 Aspect Ratio: 9:16 TikTok / Reels / Shorts
 Quality:      Fast (720p)
 Resize Mode:  Blur Background

 [✂ Start Clipping]  [⏹ Stop]  [📂 Open Clips Folder]
─────────────────────────────────────────
 [08:42:01] FFmpeg ready: ffmpeg
 [08:42:05] Starting: 6 clips × 10s | 9:16 | Blur Background
 [08:42:05] --- Clip 1/6  [0.0s to 10.0s] ---
 [08:42:05]   Progress: 00:00:05.12
 [08:42:07]   DONE: clip_01.mp4  (4.2 MB)
```

---

## Requirements

- Python 3.8+
- FFmpeg installed and accessible in PATH

### Install FFmpeg (Windows)

Open Command Prompt as Administrator and run:

```bash
winget install ffmpeg
```

Then close and reopen your terminal.

---

## Installation

```bash
# Clone the repo
git clone https://github.com/abdullahkhalidmirza/video-clipper.git
cd video-clipper

# No extra dependencies needed — uses Python standard library only
python video_clipper.py
```

---

## Usage

1. Run `python video_clipper.py`
2. Click **Browse Video** and select your file
3. Set number of clips and seconds per clip
4. Choose aspect ratio, quality, and resize mode
5. Click **✂ Start Clipping**
6. Clips save to `~/Desktop/VideoClips/` in a timestamped folder

---

## Resize Modes Explained

| Mode | What it does |
|------|-------------|
| **Black Bars** | Fits video inside frame, pads empty space with black. Safest option. |
| **Blur Background** | Scales video to fit, fills background with a blurred version of itself. Looks great on vertical clips. |
| **Center Crop** | Scales to fill the frame, crops edges. No black bars, no distortion. |
| **Stretch** | Stretches video to fill. Not recommended unless source and target ratios are close. |

---

## Output

Clips are saved as `.mp4` files using:
- **Video codec:** H.264 (`libx264`) with `ultrafast` preset
- **Audio codec:** AAC at 96k
- **Container flags:** `+faststart` for instant web playback

---

## Project Structure

```
video-clipper/
└── video_clipper.py   # Single-file app — everything in one place
```

---

## License

MIT — free to use, modify, and distribute.

---

## Author

Built by [Abdullah Khalid Mirza](https://abdullahkhalidmirza.com)
