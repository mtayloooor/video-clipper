"""
Video Clipper — Fast & Free
Uses FFmpeg with ultrafast preset for quick clipping
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import subprocess
import os
import re
import platform
import queue
import shutil
import time
from datetime import datetime
from pathlib import Path

IS_MAC     = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

if IS_MAC:
    FFMPEG_INSTALL_HINT = "brew install ffmpeg"
    FFMPEG_INSTALL_HELP = "Open Terminal and run:\n   brew install ffmpeg\nThen restart this app."
elif IS_WINDOWS:
    FFMPEG_INSTALL_HINT = "winget install ffmpeg"
    FFMPEG_INSTALL_HELP = "Run in Command Prompt (Admin):\n   winget install ffmpeg\nThen restart this app."
else:
    FFMPEG_INSTALL_HINT = "sudo apt install ffmpeg"
    FFMPEG_INSTALL_HELP = "Install FFmpeg with your package manager, e.g.:\n   sudo apt install ffmpeg\nThen restart this app."


# ═══════════════════════════════════════════════════════
#  FFMPEG HELPERS
# ═══════════════════════════════════════════════════════

def find_ffmpeg():
    candidates = []
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    candidates += ["ffmpeg", "ffmpeg.exe"]
    if IS_WINDOWS:
        candidates += [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe"),
        ]
    elif IS_MAC:
        # Apps launched from Finder/IDEs often don't inherit the shell PATH,
        # so check the usual Homebrew / MacPorts locations directly.
        candidates += [
            "/opt/homebrew/bin/ffmpeg",   # Homebrew (Apple Silicon)
            "/usr/local/bin/ffmpeg",      # Homebrew (Intel)
            "/opt/local/bin/ffmpeg",      # MacPorts
        ]
    for c in candidates:
        try:
            r = subprocess.run([c, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return None


def get_duration(ff, path):
    """Get video duration in seconds using ffmpeg -i."""
    try:
        r = subprocess.run(
            [ff, "-i", path],
            capture_output=True, text=True, timeout=15,
            errors="replace"
        )
        # ffmpeg writes to stderr
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
        if m:
            h, mn, s = m.groups()
            return int(h) * 3600 + int(mn) * 60 + float(s)
    except Exception:
        pass
    return None


def get_video_size(ff, path):
    """Get width x height."""
    try:
        r = subprocess.run(
            [ff, "-i", path],
            capture_output=True, text=True, timeout=15,
            errors="replace"
        )
        m = re.search(r"Stream.*?Video.*?(\d{2,5})x(\d{2,5})", r.stderr)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None


def get_video_codec(ff, path):
    """Get the source video codec name, e.g. 'h264' or 'hevc'."""
    try:
        r = subprocess.run(
            [ff, "-i", path],
            capture_output=True, text=True, timeout=15,
            errors="replace"
        )
        m = re.search(r"Stream.*?Video:\s*(\w+)", r.stderr)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════
#  CLIP MAKER  — simple, fast, reliable
# ═══════════════════════════════════════════════════════

QUALITY_4K   = "4K (2160p)"
QUALITY_FULL = "Full Size (no resize)"
MIN_4K_SIDE  = 2160   # source's shorter side must be at least this for 4K

QUALITY_PRESETS = {
    "Fast (720p)":  {"w9": 720,  "h9": 1280, "w1": 720,  "h1": 720,  "crf": 26},
    "Good (1080p)": {"w9": 1080, "h9": 1920, "w1": 1080, "h1": 1080, "crf": 23},
    QUALITY_4K:     {"w9": 2160, "h9": 3840, "w1": 2160, "h1": 2160, "crf": 20},
}


def supports_4k(src_w, src_h):
    return bool(src_w and src_h and min(src_w, src_h) >= MIN_4K_SIDE)


def quality_options(src_w=None, src_h=None):
    """Quality choices for the dropdown — 4K only if the source is big enough."""
    opts = [k for k in QUALITY_PRESETS if k != QUALITY_4K or supports_4k(src_w, src_h)]
    return opts + [QUALITY_FULL]

ASPECT_PRESETS = {
    "9:16  TikTok / Reels / Shorts": "9:16",
    "1:1   Instagram Square":        "1:1",
    "16:9  YouTube Landscape":       "16:9",
    "4:5   Instagram Portrait":      "4:5",
}

def get_out_dims(aspect_str, quality_dict):
    if aspect_str == "9:16":
        return quality_dict["w9"], quality_dict["h9"]
    elif aspect_str == "1:1":
        return quality_dict["w1"], quality_dict["h1"]
    elif aspect_str == "16:9":
        return quality_dict["h9"], quality_dict["w9"]  # flip
    elif aspect_str == "4:5":
        w = quality_dict["w1"]
        return w, int(w * 5 / 4)
    return quality_dict["w9"], quality_dict["h9"]


def build_filter(out_w, out_h, mode):
    """
    Returns (filter_flag, filter_value).
    All filters tested and working on Windows and macOS FFmpeg.
    """
    if mode == "pad":
        # Safest / fastest — fit inside, pad black
        vf = (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"
        )
        return ["-vf", vf]

    elif mode == "crop":
        # Scale to fill, center crop
        vf = (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}"
        )
        return ["-vf", vf]

    elif mode == "blur":
        # Reference [0:v] twice — no split needed, simpler and works on all FFmpeg versions
        # Scale BG down before blur for SPEED (blur on small image then upscale)
        bg_small_w = out_w // 4
        bg_small_h = out_h // 4
        fc = (
            f"[0:v]scale={bg_small_w}:{bg_small_h}:force_original_aspect_ratio=increase,"
            f"crop={bg_small_w}:{bg_small_h},"
            f"boxblur=10:2,"
            f"scale={out_w}:{out_h}[bg];"
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
        )
        return ["-filter_complex", fc, "-map", "[out]", "-map", "0:a?"]

    elif mode == "stretch":
        return ["-vf", f"scale={out_w}:{out_h}"]

    # default fallback
    return ["-vf", f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"]


def make_one_clip(ff, inp, out_path, start, dur, out_w, out_h, mode, crf, log_fn, stop_event):
    """Cut and encode one clip. Returns True on success."""
    if stop_event.is_set():
        return False

    filter_args = build_filter(out_w, out_h, mode)

    cmd = (
        [ff, "-y",
         "-ss", f"{start:.2f}",
         "-i", inp,
         "-t",  f"{dur:.2f}"]
        + filter_args
        + [
            "-c:v", "libx264",
            "-preset", "ultrafast",   # KEY: much faster than 'fast'
            "-crf", str(crf),
            "-c:a", "aac",
            "-b:a", "96k",
            "-threads", "0",          # use all CPU cores
            "-movflags", "+faststart",
            out_path
        ]
    )

    log_fn(f"  Running FFmpeg...")
    return run_ffmpeg(cmd, out_path, log_fn, stop_event)


def make_full_size_clip(ff, inp, out_path, start, dur, vcodec, log_fn, stop_event):
    """
    Cut one clip at the source's own size. Tries a lossless stream copy first
    (instant, but the cut snaps to the nearest keyframe); if the source codecs
    can't go into an MP4, re-encodes at the original resolution instead.
    """
    if stop_event.is_set():
        return False

    copy_cmd = [ff, "-y",
                "-ss", f"{start:.2f}",
                "-i", inp,
                "-t", f"{dur:.2f}",
                "-map", "0:v:0", "-map", "0:a?",
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart"]
    if vcodec == "hevc":
        copy_cmd += ["-tag:v", "hvc1"]   # lets QuickTime / Finder play HEVC MP4s
    copy_cmd.append(out_path)

    log_fn("  Passthrough (stream copy, no re-encode)...")
    if run_ffmpeg(copy_cmd, out_path, log_fn, stop_event):
        return True
    if stop_event.is_set():
        return False

    log_fn("  Passthrough not possible for this source — re-encoding at original size...")
    encode_cmd = [ff, "-y",
                  "-ss", f"{start:.2f}",
                  "-i", inp,
                  "-t", f"{dur:.2f}",
                  "-map", "0:v:0", "-map", "0:a?",
                  "-c:v", "libx264",
                  "-preset", "ultrafast",
                  "-crf", "18",
                  "-pix_fmt", "yuv420p",
                  "-c:a", "aac",
                  "-b:a", "192k",
                  "-threads", "0",
                  "-movflags", "+faststart",
                  out_path]
    return run_ffmpeg(encode_cmd, out_path, log_fn, stop_event)


def run_ffmpeg(cmd, out_path, log_fn, stop_event):
    """Run an FFmpeg command, streaming progress to the log. Returns True on success."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace"
        )

        stderr_lines = []
        last_progress = ""

        while True:
            if stop_event.is_set():
                proc.kill()
                proc.wait()
                return False

            line = proc.stderr.readline()
            if not line and proc.poll() is not None:
                break

            line = line.strip()
            if not line:
                continue

            stderr_lines.append(line)

            # Show time= progress in real time
            if "time=" in line:
                m = re.search(r"time=(\S+)", line)
                if m and m.group(1) != last_progress:
                    last_progress = m.group(1)
                    log_fn(f"  Progress: {last_progress}")
            elif any(x in line.lower() for x in ["error", "invalid", "unable", "no such", "failed"]):
                log_fn(f"  [!] {line}")

        proc.wait()

        if proc.returncode != 0:
            log_fn(f"  FFmpeg exited with code {proc.returncode}")
            # Print last 5 meaningful lines
            for l in stderr_lines[-10:]:
                if l.strip() and "frame=" not in l:
                    log_fn(f"    {l}")
            return False

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 500:
            log_fn("  Output file empty or missing")
            return False

        return True

    except Exception as e:
        log_fn(f"  Error: {e}")
        return False


# ═══════════════════════════════════════════════════════
#  MAIN RUNNER
# ═══════════════════════════════════════════════════════

def run_clipping(inp, out_base, num_clips, clip_dur,
                 aspect_str, mode, quality_key,
                 log_fn, prog_fn, done_fn, stop_event):

    ff = find_ffmpeg()
    if not ff:
        log_fn(f"ERROR: FFmpeg not found. Run:  {FFMPEG_INSTALL_HINT}")
        done_fn(0, None)
        return

    log_fn(f"FFmpeg: {ff}")

    total = get_duration(ff, inp)
    if total is None:
        log_fn("ERROR: Cannot read video duration. Is the file valid?")
        done_fn(0, None)
        return

    src_w, src_h = get_video_size(ff, inp)
    full_size = quality_key == QUALITY_FULL
    vcodec = get_video_codec(ff, inp) if full_size else None

    if quality_key == QUALITY_4K and not supports_4k(src_w, src_h):
        log_fn(f"Source is smaller than 4K — using Good (1080p) instead")
        quality_key = "Good (1080p)"

    if full_size:
        crf = None
        out_w, out_h = src_w, src_h
        mode = "passthrough"
    else:
        q   = QUALITY_PRESETS[quality_key]
        crf = q["crf"]
        out_w, out_h = get_out_dims(aspect_str, q)

    log_fn(f"File     : {Path(inp).name}")
    log_fn(f"Source   : {src_w or '?'}x{src_h or '?'}  →  Output: {out_w or '?'}x{out_h or '?'}")
    log_fn(f"Duration : {total:.1f}s")
    if clip_dur is None:
        # Split whole video: equal back-to-back clips covering the full length
        clip_dur = total / num_clips
        log_fn(f"Clips    : whole video → {num_clips} x {clip_dur:.1f}s  |  Mode: {mode}  |  Quality: {quality_key}")
    else:
        log_fn(f"Clips    : {num_clips} x {clip_dur}s  |  Mode: {mode}  |  Quality: {quality_key}")
    log_fn("")

    # Adjust if video too short
    if num_clips * clip_dur > total + 0.01:
        clip_dur = total / num_clips
        log_fn(f"Video shorter than needed — using {clip_dur:.1f}s per clip")

    # Evenly spread start times
    if num_clips == 1:
        starts = [0.0]
    else:
        gap = (total - clip_dur) / (num_clips - 1)
        starts = [i * gap for i in range(num_clips)]

    # Create output folder
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem   = Path(inp).stem[:25]
    folder = os.path.join(out_base, f"{stem}_clips_{ts}")
    os.makedirs(folder, exist_ok=True)
    log_fn(f"Saving to: {folder}\n")

    saved = 0
    for i, start in enumerate(starts):
        if stop_event.is_set():
            log_fn("Stopped by user.")
            break

        name     = f"clip_{i+1:02d}.mp4"
        out_path = os.path.join(folder, name)

        log_fn(f"--- Clip {i+1}/{num_clips}  [{start:.1f}s to {start+clip_dur:.1f}s] ---")

        if full_size:
            ok = make_full_size_clip(
                ff, inp, out_path, start, clip_dur, vcodec, log_fn, stop_event
            )
        else:
            ok = make_one_clip(
                ff, inp, out_path, start, clip_dur,
                out_w, out_h, mode, crf, log_fn, stop_event
            )

        if ok:
            mb = os.path.getsize(out_path) / 1024 / 1024
            log_fn(f"  DONE: {name}  ({mb:.1f} MB)\n")
            saved += 1
        else:
            log_fn(f"  FAILED: {name}\n")
            if i == 0 and mode == "blur":
                log_fn("  TIP: Blur mode failed — try switching to 'Black Bars' mode and retry.\n")

        prog_fn(i + 1, num_clips)

    log_fn(f"{'='*40}")
    if saved:
        log_fn(f"Done! {saved}/{num_clips} clips saved.")
        log_fn(f"Folder: {folder}")
    else:
        log_fn("No clips saved. Check errors above.")
        log_fn("Try: switch mode to 'Black Bars (Safest)' and try again.")

    done_fn(saved, folder if saved else None)


# ═══════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════

BG      = "#0f0f13"
CARD    = "#1a1a24"
BORDER  = "#2e2e3e"
ACCENT  = "#c084fc"
GREEN   = "#4ade80"
RED     = "#f87171"
YELLOW  = "#fbbf24"
TEXT    = "#f1f0ff"
SUBTEXT = "#7c7c9e"
PURPLE  = "#7c3aed"
DIM     = "#4a4a60"   # labels / text of disabled controls

# Fonts: Segoe UI / Cascadia Code only exist on Windows. Tk on macOS also
# renders point sizes ~25% smaller, so scale them up to match.
if IS_MAC:
    UI_FAMILY, MONO_FAMILY, FONT_SCALE = "Helvetica Neue", "Menlo", 1.3
elif IS_WINDOWS:
    UI_FAMILY, MONO_FAMILY, FONT_SCALE = "Segoe UI", "Cascadia Code", 1.0
else:
    UI_FAMILY, MONO_FAMILY, FONT_SCALE = "DejaVu Sans", "DejaVu Sans Mono", 1.0


def F(size, *style, mono=False):
    return (MONO_FAMILY if mono else UI_FAMILY, round(size * FONT_SCALE), *style)


class FlatButton(tk.Label):
    """
    Label-based button. macOS native tk.Button ignores bg colours, which made
    the white button text invisible — a Label renders the same on every OS.
    """
    def __init__(self, parent, command=None, activebackground=None,
                 state="normal", **kw):
        kw.setdefault("cursor", "hand2")
        kw.setdefault("disabledforeground", SUBTEXT)
        super().__init__(parent, **kw)
        self._command  = command
        self._bg       = kw.get("bg", CARD)
        self._hover_bg = activebackground
        self._state    = "normal"
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.configure(state=state)

    def _click(self, _e):
        if self._state != "disabled" and self._command:
            self._command()

    def _hover(self, inside):
        if self._hover_bg and self._state != "disabled":
            super().configure(bg=self._hover_bg if inside else self._bg)

    def configure(self, cnf=None, **kw):
        if "bg" in kw:
            self._bg = kw["bg"]
        if "state" in kw:
            self._state = kw["state"]
            kw["cursor"] = "arrow" if self._state == "disabled" else "hand2"
            if self._state == "disabled":
                kw.setdefault("bg", self._bg)
        return super().configure(cnf, **kw)

    config = configure


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Clipper  —  Fast & Free")
        self.geometry("820x820")
        self.minsize(700, 700)
        self.configure(bg=BG)

        self._running    = False
        self._stop_evt   = threading.Event()
        self._out_folder = None
        self._inp_path   = ""

        # Tk must only be touched from the main thread (macOS crashes otherwise),
        # so the worker thread posts UI updates here and _pump_ui runs them.
        self._ui_q = queue.Queue()

        self.out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "VideoClips")
        os.makedirs(self.out_dir, exist_ok=True)

        self._setup_styles()
        self._build()
        self.after(50, self._pump_ui)
        self.after(400, self._startup_check)

    def _ui(self, fn):
        self._ui_q.put(fn)

    def _pump_ui(self):
        try:
            while True:
                self._ui_q.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._pump_ui)

    def _setup_styles(self):
        sty = ttk.Style(self)
        if IS_MAC:
            # The native 'aqua' theme ignores custom colours on the
            # progress bar and comboboxes; 'clam' respects them.
            sty.theme_use("clam")
            sty.configure("TCombobox", fieldbackground="#21202e", background=BORDER,
                          foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER,
                          lightcolor=BORDER, darkcolor=BORDER)
            sty.map("TCombobox",
                    fieldbackground=[("disabled", BG), ("readonly", "#21202e")],
                    foreground=[("disabled", DIM), ("readonly", TEXT)],
                    arrowcolor=[("disabled", DIM)],
                    selectbackground=[("readonly", "#21202e")],
                    selectforeground=[("readonly", TEXT)])
            self.option_add("*TCombobox*Listbox.background", CARD)
            self.option_add("*TCombobox*Listbox.foreground", TEXT)
            self.option_add("*TCombobox*Listbox.selectBackground", PURPLE)
            self.option_add("*TCombobox*Listbox.selectForeground", "white")
        sty.configure("P.Horizontal.TProgressbar",
                      troughcolor="#21202e", background=ACCENT,
                      bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)

    def _startup_check(self):
        ff = find_ffmpeg()
        if ff:
            self._log(f"FFmpeg ready: {ff}", "g")
        else:
            self._log("FFmpeg not found!", "r")
            for line in FFMPEG_INSTALL_HELP.splitlines():
                self._log(line, "y")

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build(self):
        # Header
        h = tk.Frame(self, bg=BG)
        h.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(h, text="✂  Video Clipper",
                 font=F(18, "bold"), bg=BG, fg=TEXT).pack(side="left")
        tk.Label(h, text="  100% Free  •  No Watermark  •  Works Offline • abdullahkhalidmirza.com",
                 font=F(9), bg=BG, fg=SUBTEXT).pack(side="left", pady=(4, 0))
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=6)

        # ── Video select ──────────────────────────────────────────────────────
        fc = self._card()
        fc.pack(fill="x", padx=20, pady=4)
        fi = tk.Frame(fc, bg=CARD)
        fi.pack(fill="x", padx=14, pady=10)
        self._file_lbl = tk.Label(fi,
            text="No video selected — click Browse",
            font=F(10), bg=CARD, fg=SUBTEXT)
        self._file_lbl.pack(side="left", fill="x", expand=True)
        FlatButton(fi, text="📁  Browse Video",
                  font=F(10, "bold"),
                  bg=PURPLE, fg="white", activebackground="#6d28d9",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=self._pick).pack(side="right")

        # ── Settings ──────────────────────────────────────────────────────────
        sc = self._card()
        sc.pack(fill="x", padx=20, pady=6)

        # Row 1: clips, duration, summary
        r1 = tk.Frame(sc, bg=CARD)
        r1.pack(fill="x", padx=14, pady=(12, 6))

        self._n_clips   = tk.IntVar(value=6)
        self._clip_s    = tk.IntVar(value=10)
        self._whole_vid = tk.BooleanVar(value=False)
        self._src_dur   = None   # duration of the selected video, if known

        self._spinrow(r1, "Number of Clips",  self._n_clips, 1, 100)
        self._secs_lbl, self._secs_sb = self._spinrow(
            r1, "Seconds Per Clip", self._clip_s, 1, 600, padx=28)

        sf = tk.Frame(r1, bg=CARD)
        sf.pack(side="left", padx=28)
        tk.Label(sf, text="Total", font=F(9, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w")
        self._sum_lbl = tk.Label(sf, text="6 × 10s = 60s",
                                  font=F(11, "bold"), bg=CARD, fg=GREEN)
        self._sum_lbl.pack(anchor="w", pady=(4, 0))

        # Whole-video toggle
        tr = tk.Frame(sc, bg=CARD)
        tr.pack(fill="x", padx=14, pady=(0, 10))
        self._whole_btn = FlatButton(tr, text="", font=F(10),
            bg=CARD, fg=TEXT, activebackground="#21202e",
            padx=4, pady=2, command=self._toggle_whole)
        self._whole_btn.pack(side="left")
        tk.Label(tr, text="Number of Clips sets the length of each clip",
                 font=F(8), bg=CARD, fg=SUBTEXT).pack(side="left", padx=8)

        # Row 2: aspect, quality, mode
        r2 = tk.Frame(sc, bg=CARD)
        r2.pack(fill="x", padx=14, pady=(0, 12))

        self._aspect_v  = tk.StringVar(value=list(ASPECT_PRESETS.keys())[0])
        self._quality_v = tk.StringVar(value="Fast (720p)")
        self._mode_v    = tk.StringVar(value="Black Bars (Safest)")

        self._aspect_lbl, self._aspect_cb = self._ddrow(r2, "Aspect Ratio",
                    self._aspect_v, list(ASPECT_PRESETS.keys()), w=30)
        _, self._quality_cb = self._ddrow(r2, "Quality",
                    self._quality_v, quality_options(), w=20, padx=14)
        self._mode_lbl, self._mode_cb = self._ddrow(r2, "Resize Mode",
                    self._mode_v,
                    ["Black Bars (Safest)", "Blur Background", "Center Crop", "Stretch"],
                    w=24, padx=14)
        self._quality_v.trace_add("write", lambda *_: self._upd_quality())

        # Shown under row 2 only while Full Size has disabled the dropdowns
        self._r2 = r2
        self._full_note = tk.Label(sc,
            text="ⓘ  Aspect Ratio and Resize Mode are disabled — Full Size keeps the source's own frame.",
            font=F(8), bg=CARD, fg=YELLOW, anchor="w")

        # Output folder
        of = tk.Frame(sc, bg=CARD)
        of.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(of, text="Save to:", font=F(9, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left")
        self._dir_lbl = tk.Label(of, text=self._sh(self.out_dir),
                                  font=F(9), bg=CARD, fg=ACCENT, cursor="hand2")
        self._dir_lbl.pack(side="left", padx=8)
        self._dir_lbl.bind("<Button-1>", lambda e: self._pick_dir())
        chg = tk.Label(of, text="[change]", font=F(8),
                       bg=CARD, fg=SUBTEXT, cursor="hand2")
        chg.pack(side="left")
        chg.bind("<Button-1>", lambda e: self._pick_dir())

        # ── Buttons ───────────────────────────────────────────────────────────
        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=20, pady=6)

        self._go_btn = FlatButton(br, text="✂  Start Clipping",
            font=F(11, "bold"),
            bg=PURPLE, fg="white", activebackground="#6d28d9",
            relief="flat", padx=20, pady=8, cursor="hand2",
            command=self._start)
        self._go_btn.pack(side="left")

        self._stop_btn = FlatButton(br, text="⏹  Stop",
            font=F(11, "bold"),
            bg="#2e2e3e", fg=SUBTEXT, relief="flat",
            padx=16, pady=8, cursor="hand2",
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=10)

        self._open_btn = FlatButton(br, text="📂  Open Clips Folder",
            font=F(10),
            bg="#1a1a24", fg=ACCENT, relief="flat",
            padx=12, pady=8, cursor="hand2",
            command=self._open, state="disabled")
        self._open_btn.pack(side="right")

        FlatButton(br, text="🗑 Clear",
            font=F(10),
            bg="#1a1a24", fg=SUBTEXT, relief="flat",
            padx=10, pady=8, cursor="hand2",
            command=self._clear).pack(side="right", padx=6)

        # Progress bar (style set in _setup_styles)
        self._pb = ttk.Progressbar(self, style="P.Horizontal.TProgressbar",
                                    mode="determinate", maximum=100)
        self._pb.pack(fill="x", padx=20, pady=(4, 0))

        sr = tk.Frame(self, bg=BG)
        sr.pack(fill="x", padx=20)
        self._prog_lbl  = tk.Label(sr, text="", font=F(8), bg=BG, fg=SUBTEXT)
        self._prog_lbl.pack(side="left")
        self._stat_lbl  = tk.Label(sr, text="● Idle", font=F(8), bg=BG, fg="#2e2e3e")
        self._stat_lbl.pack(side="right")

        # Log
        tk.Label(self, text="  Log", font=F(8, "bold"),
                 bg=BG, fg=SUBTEXT).pack(anchor="w", padx=20, pady=(6, 0))
        self._lb = scrolledtext.ScrolledText(
            self, wrap="word", bg="#0a0a10", fg=TEXT,
            font=F(9, mono=True), relief="flat", bd=0,
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled")
        self._lb.pack(fill="both", expand=True, padx=20, pady=(2, 14))
        for t, c in [("g", GREEN), ("r", RED), ("y", YELLOW), ("b", ACCENT), ("d", SUBTEXT)]:
            self._lb.tag_config(t, foreground=c)

        # Trace spinbox changes
        self._n_clips.trace_add("write", lambda *_: self._upd_sum())
        self._clip_s.trace_add("write",  lambda *_: self._upd_sum())
        self._upd_whole()

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _card(self):
        return tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=BORDER)

    def _spinrow(self, parent, label, var, lo, hi, padx=0):
        f = tk.Frame(parent, bg=CARD)
        f.pack(side="left", padx=(padx, 0))
        lbl = tk.Label(f, text=label, font=F(9, "bold"), bg=CARD, fg=TEXT)
        lbl.pack(anchor="w")
        sb = tk.Spinbox(f, textvariable=var, from_=lo, to=hi, width=5,
                   font=F(13, "bold"), bg="#21202e", fg=ACCENT,
                   disabledbackground=BG, disabledforeground=DIM,
                   buttonbackground=BORDER, relief="flat", insertbackground=ACCENT,
                   highlightthickness=1, highlightbackground=BORDER)
        sb.pack(anchor="w", pady=(4, 0))
        return lbl, sb

    def _ddrow(self, parent, label, var, values, w=20, padx=0):
        f = tk.Frame(parent, bg=CARD)
        f.pack(side="left", padx=(padx, 0))
        lbl = tk.Label(f, text=label, font=F(9, "bold"), bg=CARD, fg=TEXT)
        lbl.pack(anchor="w")
        cb = ttk.Combobox(f, textvariable=var, values=values,
                           state="readonly", width=w, font=F(9))
        cb.pack(anchor="w", pady=(4, 0))
        return lbl, cb

    def _upd_quality(self):
        # Full Size keeps the source frame, so aspect ratio / resize mode don't apply
        full = self._quality_v.get() == QUALITY_FULL
        for lbl, cb in [(self._aspect_lbl, self._aspect_cb), (self._mode_lbl, self._mode_cb)]:
            cb.config(state="disabled" if full else "readonly")
            lbl.config(fg=DIM if full else TEXT)
        if full:
            self._full_note.pack(fill="x", padx=14, pady=(0, 10), after=self._r2)
        else:
            self._full_note.pack_forget()

    def _toggle_whole(self):
        self._whole_vid.set(not self._whole_vid.get())
        self._upd_whole()

    def _upd_whole(self):
        whole = self._whole_vid.get()
        self._whole_btn.config(
            text=("☑" if whole else "☐") + "  Split entire video into clips",
            fg=GREEN if whole else TEXT)
        self._secs_sb.config(state="disabled" if whole else "normal")
        self._secs_lbl.config(fg=DIM if whole else TEXT)
        self._upd_sum()

    def _sh(self, p, n=48):
        return p if len(p) <= n else "…" + p[-(n-1):]

    def _upd_sum(self):
        try:
            n = self._n_clips.get()
            if self._whole_vid.get():
                if self._src_dur and n > 0:
                    txt = f"{n} × {self._src_dur / n:.1f}s = {self._src_dur:.1f}s (whole video)"
                else:
                    txt = f"Whole video ÷ {n}"
            else:
                d = self._clip_s.get()
                txt = f"{n} × {d}s = {n*d}s"
            self._sum_lbl.config(text=txt)
        except Exception:
            pass

    # ── Pickers ───────────────────────────────────────────────────────────────
    def _pick(self):
        p = filedialog.askopenfilename(
            title="Select Video",
            filetypes=[("Video", ("*.mp4", "*.mov", "*.avi", "*.mkv",
                                  "*.webm", "*.m4v", "*.flv", "*.wmv")),
                       ("All", "*")])
        if not p:
            return
        self._inp_path = p
        name = Path(p).name
        self._file_lbl.config(text=name, fg=GREEN)
        self._log(f"Selected: {name}", "g")
        ff = find_ffmpeg()
        if ff:
            dur = get_duration(ff, p)
            w, h = get_video_size(ff, p)
            self._src_dur = dur
            self._upd_sum()
            if dur:
                mb = os.path.getsize(p) / 1024 / 1024
                self._log(f"  {w or '?'}×{h or '?'}  |  {dur:.1f}s  |  {mb:.1f} MB", "d")
            opts = quality_options(w, h)
            self._quality_cb.config(values=opts)
            if QUALITY_4K in opts:
                self._log(f"  4K quality available for this video", "d")
            elif self._quality_v.get() == QUALITY_4K:
                self._quality_v.set("Good (1080p)")
                self._log(f"  Source is smaller than 4K — quality set to Good (1080p)", "y")

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_dir)
        if d:
            self.out_dir = d
            os.makedirs(d, exist_ok=True)
            self._dir_lbl.config(text=self._sh(d))

    def _open(self):
        folder = self._out_folder or self.out_dir
        try:
            if platform.system() == "Windows":
                os.startfile(folder)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _clear(self):
        self._lb.config(state="normal")
        self._lb.delete("1.0", "end")
        self._lb.config(state="disabled")

    # ── Log ───────────────────────────────────────────────────────────────────
    def _log(self, msg, tag=""):
        def _d():
            self._lb.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self._lb.insert("end", f"[{ts}] ", "d")
            self._lb.insert("end", msg + "\n", tag)
            self._lb.see("end")
            self._lb.config(state="disabled")
        self._ui(_d)

    def _set_prog(self, done, total):
        def _d():
            pct = int(done / total * 100) if total else 0
            self._pb["value"] = pct
            self._prog_lbl.config(text=f"Clip {done}/{total}  ({pct}%)")
        self._ui(_d)

    def _set_stat(self, txt, col):
        self._ui(lambda: self._stat_lbl.config(text=f"● {txt}", fg=col))

    # ── Start / Stop ──────────────────────────────────────────────────────────
    def _start(self):
        if not self._inp_path or not os.path.exists(self._inp_path):
            messagebox.showwarning("No Video", "Please select a video file first.")
            return
        if self._running:
            return
        if not find_ffmpeg():
            messagebox.showerror("FFmpeg Missing", "FFmpeg not found.\n\n" + FFMPEG_INSTALL_HELP)
            return

        # Map display mode to key
        mode_map = {
            "Black Bars (Safest)": "pad",
            "Blur Background":     "blur",
            "Center Crop":         "crop",
            "Stretch":             "stretch",
        }
        mode = mode_map.get(self._mode_v.get(), "pad")
        aspect = ASPECT_PRESETS.get(self._aspect_v.get(), "9:16")

        whole = self._whole_vid.get()
        try:
            n = int(self._n_clips.get())
            d = None if whole else int(self._clip_s.get())
            if n < 1 or (d is not None and d < 1):
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Enter valid numbers for clips and duration.")
            return
        d_txt = "whole video" if whole else f"{d}s"

        self._stop_evt.clear()
        self._running    = True
        self._out_folder = None
        self._pb["value"] = 0
        self._go_btn.config(state="disabled")
        self._stop_btn.config(state="normal", bg=RED, fg="white")
        self._open_btn.config(state="disabled")
        self._set_stat("Clipping…", ACCENT)

        if self._quality_v.get() == QUALITY_FULL:
            self._log(f"Starting: {n} clips × {d_txt}  |  {QUALITY_FULL}", "b")
        else:
            self._log(f"Starting: {n} clips × {d_txt}  |  {self._aspect_v.get()}  |  {self._mode_v.get()}", "b")

        threading.Thread(
            target=run_clipping,
            args=(
                self._inp_path, self.out_dir,
                n, d, aspect, mode, self._quality_v.get(),
                lambda m, t="": self._log(m, t),
                self._set_prog,
                self._done,
                self._stop_evt,
            ),
            daemon=True
        ).start()

    def _stop(self):
        if not self._running:
            return
        self._stop_evt.set()
        self._stop_btn.config(state="disabled", bg="#2e2e3e", fg=SUBTEXT)
        self._set_stat("Stopping…", YELLOW)

    def _done(self, saved, folder):
        def _d():
            self._running = False
            if folder:
                self._out_folder = folder
            self._go_btn.config(state="normal")
            self._stop_btn.config(state="disabled", bg="#2e2e3e", fg=SUBTEXT)
            self._open_btn.config(state="normal")
            if saved:
                self._pb["value"] = 100
                self._set_stat(f"Done — {saved} clips saved", GREEN)
            else:
                self._set_stat("Failed — check log", RED)
        self._ui(_d)


# ═══════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()
