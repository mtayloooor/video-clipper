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
import time
from datetime import datetime
from pathlib import Path


# ═══════════════════════════════════════════════════════
#  FFMPEG HELPERS
# ═══════════════════════════════════════════════════════

def find_ffmpeg():
    candidates = ["ffmpeg", "ffmpeg.exe"]
    if platform.system() == "Windows":
        candidates += [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe"),
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


# ═══════════════════════════════════════════════════════
#  CLIP MAKER  — simple, fast, reliable
# ═══════════════════════════════════════════════════════

QUALITY_PRESETS = {
    "Fast (720p)":  {"w9": 720,  "h9": 1280, "w1": 720,  "h1": 720,  "crf": 26},
    "Good (1080p)": {"w9": 1080, "h9": 1920, "w1": 1080, "h1": 1080, "crf": 23},
}

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
    All filters tested and working on Windows FFmpeg.
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

    # Remove duplicate -map if already added by filter_args
    log_fn(f"  Running FFmpeg...")

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
        log_fn("ERROR: FFmpeg not found. Run:  winget install ffmpeg")
        done_fn(0, None)
        return

    log_fn(f"FFmpeg: {ff}")

    total = get_duration(ff, inp)
    if total is None:
        log_fn("ERROR: Cannot read video duration. Is the file valid?")
        done_fn(0, None)
        return

    src_w, src_h = get_video_size(ff, inp)

    q   = QUALITY_PRESETS[quality_key]
    crf = q["crf"]
    out_w, out_h = get_out_dims(aspect_str, q)

    log_fn(f"File     : {Path(inp).name}")
    log_fn(f"Source   : {src_w or '?'}x{src_h or '?'}  →  Output: {out_w}x{out_h}")
    log_fn(f"Duration : {total:.1f}s")
    log_fn(f"Clips    : {num_clips} x {clip_dur}s  |  Mode: {mode}  |  Quality: {quality_key}")
    log_fn("")

    # Adjust if video too short
    if num_clips * clip_dur > total:
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

        self.out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "VideoClips")
        os.makedirs(self.out_dir, exist_ok=True)

        self._build()
        self.after(400, self._startup_check)

    def _startup_check(self):
        ff = find_ffmpeg()
        if ff:
            self._log(f"FFmpeg ready: {ff}", "green")
        else:
            self._log("FFmpeg not found!", "red")
            self._log("Fix: open Command Prompt as Admin and run:", "yellow")
            self._log("     winget install ffmpeg", "yellow")
            self._log("Then close/reopen Command Prompt and restart this app.\n", "dim")

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build(self):
        # Header
        h = tk.Frame(self, bg=BG)
        h.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(h, text="✂  Video Clipper",
                 font=("Segoe UI", 18, "bold"), bg=BG, fg=TEXT).pack(side="left")
        tk.Label(h, text="  100% Free  •  No Watermark  •  Works Offline • abdullahkhalidmirza.com",
                 font=("Segoe UI", 9), bg=BG, fg=SUBTEXT).pack(side="left", pady=(4, 0))
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=6)

        # ── Video select ──────────────────────────────────────────────────────
        fc = self._card()
        fc.pack(fill="x", padx=20, pady=4)
        fi = tk.Frame(fc, bg=CARD)
        fi.pack(fill="x", padx=14, pady=10)
        self._file_lbl = tk.Label(fi,
            text="No video selected — click Browse",
            font=("Segoe UI", 10), bg=CARD, fg=SUBTEXT)
        self._file_lbl.pack(side="left", fill="x", expand=True)
        tk.Button(fi, text="📁  Browse Video",
                  font=("Segoe UI", 10, "bold"),
                  bg=PURPLE, fg="white", activebackground="#6d28d9",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=self._pick).pack(side="right")

        # ── Settings ──────────────────────────────────────────────────────────
        sc = self._card()
        sc.pack(fill="x", padx=20, pady=6)

        # Row 1: clips, duration, summary
        r1 = tk.Frame(sc, bg=CARD)
        r1.pack(fill="x", padx=14, pady=(12, 6))

        self._n_clips = tk.IntVar(value=6)
        self._clip_s  = tk.IntVar(value=10)

        self._spinrow(r1, "Number of Clips",  self._n_clips, 1, 100)
        self._spinrow(r1, "Seconds Per Clip", self._clip_s,  1, 600, padx=28)

        sf = tk.Frame(r1, bg=CARD)
        sf.pack(side="left", padx=28)
        tk.Label(sf, text="Total", font=("Segoe UI", 9, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w")
        self._sum_lbl = tk.Label(sf, text="6 × 10s = 60s",
                                  font=("Segoe UI", 11, "bold"), bg=CARD, fg=GREEN)
        self._sum_lbl.pack(anchor="w", pady=(4, 0))

        # Row 2: aspect, quality, mode
        r2 = tk.Frame(sc, bg=CARD)
        r2.pack(fill="x", padx=14, pady=(0, 12))

        self._aspect_v  = tk.StringVar(value=list(ASPECT_PRESETS.keys())[0])
        self._quality_v = tk.StringVar(value="Fast (720p)")
        self._mode_v    = tk.StringVar(value="Black Bars (Safest)")

        self._ddrow(r2, "Aspect Ratio",
                    self._aspect_v, list(ASPECT_PRESETS.keys()), w=30)
        self._ddrow(r2, "Quality",
                    self._quality_v, list(QUALITY_PRESETS.keys()), w=16, padx=14)
        self._ddrow(r2, "Resize Mode",
                    self._mode_v,
                    ["Black Bars (Safest)", "Blur Background", "Center Crop", "Stretch"],
                    w=24, padx=14)

        # Output folder
        of = tk.Frame(sc, bg=CARD)
        of.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(of, text="Save to:", font=("Segoe UI", 9, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left")
        self._dir_lbl = tk.Label(of, text=self._sh(self.out_dir),
                                  font=("Segoe UI", 9), bg=CARD, fg=ACCENT, cursor="hand2")
        self._dir_lbl.pack(side="left", padx=8)
        self._dir_lbl.bind("<Button-1>", lambda e: self._pick_dir())
        tk.Label(of, text="[change]", font=("Segoe UI", 8),
                 bg=CARD, fg=SUBTEXT, cursor="hand2").pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────────
        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=20, pady=6)

        self._go_btn = tk.Button(br, text="✂  Start Clipping",
            font=("Segoe UI", 11, "bold"),
            bg=PURPLE, fg="white", activebackground="#6d28d9",
            relief="flat", padx=20, pady=8, cursor="hand2",
            command=self._start)
        self._go_btn.pack(side="left")

        self._stop_btn = tk.Button(br, text="⏹  Stop",
            font=("Segoe UI", 11, "bold"),
            bg="#2e2e3e", fg=SUBTEXT, relief="flat",
            padx=16, pady=8, cursor="hand2",
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=10)

        self._open_btn = tk.Button(br, text="📂  Open Clips Folder",
            font=("Segoe UI", 10),
            bg="#1a1a24", fg=ACCENT, relief="flat",
            padx=12, pady=8, cursor="hand2",
            command=self._open, state="disabled")
        self._open_btn.pack(side="right")

        tk.Button(br, text="🗑 Clear",
            font=("Segoe UI", 10),
            bg="#1a1a24", fg=SUBTEXT, relief="flat",
            padx=10, pady=8, cursor="hand2",
            command=self._clear).pack(side="right", padx=6)

        # Progress bar
        sty = ttk.Style()
        sty.configure("P.Horizontal.TProgressbar",
                       troughcolor="#21202e", background=ACCENT,
                       bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        self._pb = ttk.Progressbar(self, style="P.Horizontal.TProgressbar",
                                    mode="determinate", maximum=100)
        self._pb.pack(fill="x", padx=20, pady=(4, 0))

        sr = tk.Frame(self, bg=BG)
        sr.pack(fill="x", padx=20)
        self._prog_lbl  = tk.Label(sr, text="", font=("Segoe UI", 8), bg=BG, fg=SUBTEXT)
        self._prog_lbl.pack(side="left")
        self._stat_lbl  = tk.Label(sr, text="● Idle", font=("Segoe UI", 8), bg=BG, fg="#2e2e3e")
        self._stat_lbl.pack(side="right")

        # Log
        tk.Label(self, text="  Log", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=SUBTEXT).pack(anchor="w", padx=20, pady=(6, 0))
        self._lb = scrolledtext.ScrolledText(
            self, wrap="word", bg="#0a0a10", fg=TEXT,
            font=("Cascadia Code", 9), relief="flat", bd=0,
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled")
        self._lb.pack(fill="both", expand=True, padx=20, pady=(2, 14))
        for t, c in [("g", GREEN), ("r", RED), ("y", YELLOW), ("b", ACCENT), ("d", SUBTEXT)]:
            self._lb.tag_config(t, foreground=c)

        # Trace spinbox changes
        self._n_clips.trace_add("write", lambda *_: self._upd_sum())
        self._clip_s.trace_add("write",  lambda *_: self._upd_sum())

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _card(self):
        return tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=BORDER)

    def _spinrow(self, parent, label, var, lo, hi, padx=0):
        f = tk.Frame(parent, bg=CARD)
        f.pack(side="left", padx=(padx, 0))
        tk.Label(f, text=label, font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Spinbox(f, textvariable=var, from_=lo, to=hi, width=5,
                   font=("Segoe UI", 13, "bold"), bg="#21202e", fg=ACCENT,
                   buttonbackground=BORDER, relief="flat",
                   highlightthickness=1, highlightbackground=BORDER).pack(anchor="w", pady=(4, 0))

    def _ddrow(self, parent, label, var, values, w=20, padx=0):
        f = tk.Frame(parent, bg=CARD)
        f.pack(side="left", padx=(padx, 0))
        tk.Label(f, text=label, font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).pack(anchor="w")
        cb = ttk.Combobox(f, textvariable=var, values=values,
                           state="readonly", width=w, font=("Segoe UI", 9))
        cb.pack(anchor="w", pady=(4, 0))

    def _sh(self, p, n=48):
        return p if len(p) <= n else "…" + p[-(n-1):]

    def _upd_sum(self):
        try:
            n, d = self._n_clips.get(), self._clip_s.get()
            self._sum_lbl.config(text=f"{n} × {d}s = {n*d}s")
        except Exception:
            pass

    # ── Pickers ───────────────────────────────────────────────────────────────
    def _pick(self):
        p = filedialog.askopenfilename(
            title="Select Video",
            filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.flv *.wmv"),
                       ("All", "*.*")])
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
            if dur:
                mb = os.path.getsize(p) / 1024 / 1024
                self._log(f"  {w or '?'}×{h or '?'}  |  {dur:.1f}s  |  {mb:.1f} MB", "d")

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
        self.after(0, _d)

    def _set_prog(self, done, total):
        def _d():
            pct = int(done / total * 100) if total else 0
            self._pb["value"] = pct
            self._prog_lbl.config(text=f"Clip {done}/{total}  ({pct}%)")
        self.after(0, _d)

    def _set_stat(self, txt, col):
        self.after(0, lambda: self._stat_lbl.config(text=f"● {txt}", fg=col))

    # ── Start / Stop ──────────────────────────────────────────────────────────
    def _start(self):
        if not self._inp_path or not os.path.exists(self._inp_path):
            messagebox.showwarning("No Video", "Please select a video file first.")
            return
        if self._running:
            return
        if not find_ffmpeg():
            messagebox.showerror("FFmpeg Missing",
                "FFmpeg not found.\n\nRun in Command Prompt (Admin):\n   winget install ffmpeg\nThen restart this app.")
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

        try:
            n = int(self._n_clips.get())
            d = int(self._clip_s.get())
        except Exception:
            messagebox.showerror("Error", "Enter valid numbers for clips and duration.")
            return

        self._stop_evt.clear()
        self._running    = True
        self._out_folder = None
        self._pb["value"] = 0
        self._go_btn.config(state="disabled")
        self._stop_btn.config(state="normal", bg=RED, fg="white")
        self._open_btn.config(state="disabled")
        self._set_stat("Clipping…", ACCENT)

        self._log(f"Starting: {n} clips × {d}s  |  {self._aspect_v.get()}  |  {self._mode_v.get()}", "b")

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
        self._running = False
        if folder:
            self._out_folder = folder
        def _d():
            self._go_btn.config(state="normal")
            self._stop_btn.config(state="disabled", bg="#2e2e3e", fg=SUBTEXT)
            self._open_btn.config(state="normal")
            if saved:
                self._pb["value"] = 100
                self._set_stat(f"Done — {saved} clips saved", GREEN)
            else:
                self._set_stat("Failed — check log", RED)
        self.after(0, _d)


# ═══════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()