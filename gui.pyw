"""
YouTube Downloader GUI - หน้าต่างสำหรับดาวน์โหลดวิดีโอ/เสียงด้วย bin\\yt-dlp.exe

เปิดด้วย gui.bat (หรือดับเบิลคลิกไฟล์นี้) - ต้องรัน setup.bat ก่อนครั้งแรก
ใช้แค่ Python มาตรฐาน (tkinter) ไม่ต้องติดตั้งแพ็กเกจเพิ่ม
"""
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"
YTDLP = BIN_DIR / "yt-dlp.exe"
FFMPEG = BIN_DIR / "ffmpeg.exe"
CONFIG = ROOT / "yt-dlp.conf"
SETTINGS_FILE = ROOT / "gui_settings.json"
DEFAULT_OUT_DIR = ROOT / "downloads"

# โหมดเดียวกับ download.ps1
MODES = {
    "best": "วิดีโอ คุณภาพสูงสุด (MP4)",
    "1080": "วิดีโอ 1080p (MP4)",
    "720": "วิดีโอ 720p (MP4)",
    "mp3": "เสียงอย่างเดียว (MP3)",
}

# ให้ yt-dlp พิมพ์ progress เป็นบรรทัดที่แยกค่าได้ง่าย: __PROGRESS__<เปอร์เซ็นต์>|<ความเร็ว>|<เวลาที่เหลือ>|<ชื่อคลิป>
PROGRESS_TAG = "__PROGRESS__"
PROGRESS_TEMPLATE = (f"download:{PROGRESS_TAG}%(progress._percent_str)s|%(progress._speed_str)s"
                     "|%(progress._eta_str)s|%(info.title)s")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PERCENT_RE = re.compile(r"([\d.]+)%")
ITEM_RE = re.compile(r"^\[download\] Downloading item (\d+) of (\d+)")
FORMATS_RE = re.compile(r"^\[info\] .+: Downloading \d+ format\(s\): (\S+)")
STAGES = {
    "[Merger]": "กำลังรวมภาพและเสียง...",
    "[ExtractAudio]": "กำลังแปลงเป็น MP3...",
    "[Metadata]": "กำลังใส่ข้อมูลไฟล์...",
    "[EmbedThumbnail]": "กำลังใส่ภาพปก...",
}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def format_args(mode):
    if mode == "mp3":
        return ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0", "--embed-thumbnail"]
    sort = "res,ext:mp4:m4a" if mode == "best" else f"res:{mode},ext:mp4:m4a"
    return ["-f", "bv*+ba/b", "-S", sort, "--merge-output-format", "mp4"]


def is_playlist_only(url):
    """ลิงก์เพลย์ลิสต์ล้วน (ไม่ได้เจาะจงคลิป) - yt-dlp โหลดทั้งเพลย์ลิสต์เสมอ"""
    return "/playlist" in url or ("list=" in url and "v=" not in url and "youtu.be/" not in url)


def build_command(url, mode, out_dir, playlist):
    playlist = playlist or is_playlist_only(url)
    if playlist:
        template = "%(playlist_title,playlist_id)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s"
    else:
        template = "%(title)s [%(id)s].%(ext)s"

    cmd = [
        str(YTDLP),
        "--ffmpeg-location", str(BIN_DIR),
        "-P", str(out_dir),
        "-o", template,
        "--embed-metadata",
        "--no-mtime",
        "--encoding", "utf-8",
        "--newline",
        "--progress-template", PROGRESS_TEMPLATE,
    ]
    if not playlist:
        cmd.append("--no-playlist")
    # YouTube ต้องใช้ JavaScript runtime - ถ้ามี Node.js ในเครื่องก็ใช้ (Deno ใช้ได้อัตโนมัติอยู่แล้ว)
    if shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    if CONFIG.exists():
        cmd += ["--config-locations", str(CONFIG)]
    return cmd + format_args(mode) + ["--", url]


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Worker(threading.Thread):
    """รันคำสั่ง yt-dlp ทีละคำสั่งในเธรดแยก แล้วส่งผลกลับให้หน้าจอผ่าน queue"""

    def __init__(self, commands, events):
        super().__init__(daemon=True)
        self.commands = commands
        self.events = events
        self.proc = None
        self.cancelled = False

    def run(self):
        failed = 0
        for i, cmd in enumerate(self.commands, 1):
            if self.cancelled:
                break
            self.events.put(("job", i, len(self.commands)))
            try:
                self.proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
            except OSError as e:
                self.events.put(("line", f"ERROR: {e}"))
                failed += 1
                continue
            for line in self.proc.stdout:
                self.events.put(("line", ANSI_RE.sub("", line.rstrip())))
            if self.proc.wait() != 0 and not self.cancelled:
                failed += 1
        self.events.put(("done", failed, self.cancelled))

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            # /T ปิด ffmpeg ที่ yt-dlp เปิดไว้ด้วย
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                           capture_output=True, creationflags=NO_WINDOW)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.events = queue.Queue()
        self.worker = None
        self.job_kind = None

        settings = load_settings()
        mode = settings.get("mode")
        self.mode = tk.StringVar(value=mode if mode in MODES else "best")
        self.playlist = tk.BooleanVar(value=bool(settings.get("playlist", False)))
        self.out_dir = tk.StringVar(value=settings.get("out_dir") or str(DEFAULT_OUT_DIR))
        self.status = tk.StringVar(value="พร้อมดาวน์โหลด")
        self.detail = tk.StringVar()
        self._reset_position()

        self._setup_fonts()
        self._build_ui()
        scale = self.tk.call("tk", "scaling") / (96 / 72)
        self.minsize(int(640 * scale), int(600 * scale))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-Return>", lambda e: self.start_download())
        self.after(100, self.poll_events)
        if not YTDLP.exists():
            self.after(300, self.ask_setup)

    # ---------- หน้าจอ ----------

    def _setup_fonts(self):
        families = set(tkfont.families(self))
        self.family = next((f for f in ("Leelawadee UI", "Tahoma") if f in families), "TkDefaultFont")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            tkfont.nametofont(name).configure(family=self.family, size=10)
        self.bold_font = tkfont.Font(self, family=self.family, size=11, weight="bold")
        style = ttk.Style(self)
        style.configure("Big.TButton", font=self.bold_font, padding=(18, 6))
        style.configure("Status.TLabel", font=self.bold_font)

    def _build_ui(self):
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        # ลิงก์
        head = ttk.Frame(frm)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="ลิงก์ YouTube  (1 บรรทัดต่อ 1 ลิงก์)").pack(side="left")
        ttk.Button(head, text="ล้าง", command=self.clear_urls).pack(side="right")
        ttk.Button(head, text="วางลิงก์", command=self.paste_urls).pack(side="right", padx=(0, 6))
        self.urls = tk.Text(frm, height=5, wrap="none", undo=True, relief="solid", borderwidth=1,
                            font=(self.family, 10), padx=6, pady=4)
        self.urls.grid(row=1, column=0, sticky="nsew", pady=(4, 10))

        # ตัวเลือก
        opts = ttk.LabelFrame(frm, text="ตัวเลือก", padding=(10, 6))
        opts.grid(row=2, column=0, sticky="ew")
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text="รูปแบบ:").grid(row=0, column=0, sticky="nw", pady=2)
        modes = ttk.Frame(opts)
        modes.grid(row=0, column=1, columnspan=3, sticky="w")
        for i, (key, label) in enumerate(MODES.items()):
            ttk.Radiobutton(modes, text=label, value=key, variable=self.mode).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 24), pady=2)
        ttk.Checkbutton(opts, text="ดาวน์โหลดทั้งเพลย์ลิสต์ (เมื่อลิงก์อยู่ในเพลย์ลิสต์)",
                        variable=self.playlist).grid(row=1, column=1, columnspan=3, sticky="w", pady=(4, 6))
        ttk.Label(opts, text="บันทึกที่:").grid(row=2, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.out_dir).grid(row=2, column=1, sticky="ew", padx=(0, 6))
        ttk.Button(opts, text="เลือก...", command=self.choose_folder).grid(row=2, column=2, padx=(0, 6))
        ttk.Button(opts, text="เปิดโฟลเดอร์", command=self.open_folder).grid(row=2, column=3)

        # ปุ่มหลัก
        actions = ttk.Frame(frm)
        actions.grid(row=3, column=0, sticky="ew", pady=12)
        self.btn_download = ttk.Button(actions, text="ดาวน์โหลด", style="Big.TButton", command=self.start_download)
        self.btn_download.pack(side="left")
        self.btn_cancel = ttk.Button(actions, text="ยกเลิก", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=8)
        self.btn_update = ttk.Button(actions, text="อัปเดต yt-dlp", command=self.update_ytdlp)
        self.btn_update.pack(side="right")

        # สถานะ
        ttk.Label(frm, textvariable=self.status, style="Status.TLabel").grid(row=4, column=0, sticky="w")
        self.progress = ttk.Progressbar(frm, maximum=100)
        self.progress.grid(row=5, column=0, sticky="ew", pady=4)
        ttk.Label(frm, textvariable=self.detail, foreground="#555").grid(row=6, column=0, sticky="w")

        # log
        self.log_box = ScrolledText(frm, height=9, wrap="word", state="disabled", relief="solid",
                                    borderwidth=1, font=(self.family, 9), padx=6, pady=4)
        self.log_box.grid(row=7, column=0, sticky="nsew", pady=(10, 0))
        self.log_box.tag_configure("error", foreground="#c62828")
        self.log_box.tag_configure("warn", foreground="#b26a00")
        self.log_box.tag_configure("ok", foreground="#2e7d32")
        self.log_box.tag_configure("info", foreground="#1565c0")

        frm.rowconfigure(1, weight=1)
        frm.rowconfigure(7, weight=2)

    def log(self, text, tag=None):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag or ())
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_busy(self, busy):
        self.btn_download.configure(state="disabled" if busy else "normal")
        self.btn_update.configure(state="disabled" if busy else "normal")
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    # ---------- ปุ่มต่าง ๆ ----------

    def paste_urls(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return
        if text:
            current = self.urls.get("1.0", "end-1c")
            if current and not current.endswith("\n"):
                self.urls.insert("end", "\n")
            self.urls.insert("end", text + "\n")

    def clear_urls(self):
        self.urls.delete("1.0", "end")

    def get_urls(self):
        return [u.strip("\"'") for u in self.urls.get("1.0", "end").split() if u.strip("\"'")]

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.out_dir.get(), title="เลือกโฟลเดอร์ที่จะบันทึก")
        if folder:
            self.out_dir.set(str(Path(folder)))

    def open_folder(self):
        folder = Path(self.out_dir.get().strip() or DEFAULT_OUT_DIR)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            messagebox.showerror("เปิดโฟลเดอร์ไม่ได้", str(e))

    def ask_setup(self):
        if messagebox.askyesno("ยังไม่ได้ติดตั้ง",
                               "ไม่พบ bin\\yt-dlp.exe\n\nเปิด setup.bat เพื่อติดตั้งตอนนี้ไหม?\n"
                               "(ติดตั้งเสร็จแล้วกดดาวน์โหลดได้เลย)"):
            os.startfile(ROOT / "setup.bat")

    def start_download(self):
        if self.worker:
            return
        urls = self.get_urls()
        if not urls:
            messagebox.showwarning("ยังไม่มีลิงก์", "กรุณาวางลิงก์ YouTube อย่างน้อย 1 ลิงก์")
            return
        if not YTDLP.exists():
            self.ask_setup()
            return
        out_dir = Path(self.out_dir.get().strip() or DEFAULT_OUT_DIR)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("สร้างโฟลเดอร์ไม่ได้", str(e))
            return
        self.save_settings()

        mode = self.mode.get()
        self.log(f"=== {MODES[mode]} : {len(urls)} ลิงก์ -> {out_dir}", "info")
        if not FFMPEG.exists():
            self.log("คำเตือน: ไม่พบ ffmpeg.exe - จะได้แค่วิดีโอความละเอียดต่ำ และแปลง MP3 ไม่ได้ (รัน setup.bat)", "warn")
        commands = [build_command(u, mode, out_dir, self.playlist.get()) for u in urls]
        self.run_worker("download", commands, "กำลังเริ่มดาวน์โหลด...")

    def update_ytdlp(self):
        if self.worker:
            return
        if not YTDLP.exists():
            self.ask_setup()
            return
        self.log("=== อัปเดต yt-dlp", "info")
        self.run_worker("update", [[str(YTDLP), "-U"]], "กำลังอัปเดต yt-dlp...")

    def cancel(self):
        if self.worker:
            self.status.set("กำลังยกเลิก...")
            self.btn_cancel.configure(state="disabled")
            threading.Thread(target=self.worker.cancel, daemon=True).start()

    def run_worker(self, kind, commands, status):
        self.job_kind = kind
        self.progress.configure(value=0)
        self.status.set(status)
        self.detail.set("")
        self.set_busy(True)
        self.worker = Worker(commands, self.events)
        self.worker.start()

    # ---------- รับผลจาก yt-dlp ----------

    def _reset_position(self, job=0, jobs=0):
        self.job, self.jobs = job, jobs
        self.item = self.items = 0
        self.part = self.parts = 0

    def position_text(self):
        parts = []
        if self.jobs > 1:
            parts.append(f"ลิงก์ {self.job}/{self.jobs}")
        if self.items > 1:
            parts.append(f"คลิป {self.item}/{self.items}")
        if self.parts > 1:
            parts.append(f"ไฟล์ {self.part}/{self.parts}")
        return " · ".join(parts)

    def poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "line":
                    self.handle_line(event[1])
                elif event[0] == "job":
                    self._reset_position(event[1], event[2])
                elif event[0] == "done":
                    self.finish(event[1], event[2])
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    def handle_line(self, line):
        if line.startswith(PROGRESS_TAG):
            percent, speed, eta, title = (line[len(PROGRESS_TAG):].split("|", 3) + [""] * 4)[:4]
            m = PERCENT_RE.search(percent)
            if m:
                self.progress.configure(value=float(m.group(1)))
            self.status.set(f"กำลังดาวน์โหลด: {title.strip()}")
            eta = eta.strip()
            info = [percent.strip(), speed.strip()]
            if eta and eta != "NA":
                info.append(f"เหลือ {eta}")
            position = self.position_text()
            self.detail.set("   ·   ".join(([position] if position else []) + info))
            return

        if m := ITEM_RE.match(line):
            self.item, self.items = int(m.group(1)), int(m.group(2))
        elif m := FORMATS_RE.match(line):
            self.part, self.parts = 0, m.group(1).count("+") + 1
        elif line.startswith("[download] Destination:"):
            self.part += 1
        elif line.startswith("Deleting original file"):
            return  # ไฟล์ชั่วคราวหลังรวมภาพ+เสียง ไม่ต้องแสดง
        else:
            for prefix, text in STAGES.items():
                if line.startswith(prefix):
                    self.status.set(text)
                    break

        tag = "error" if line.startswith("ERROR") else "warn" if line.startswith("WARNING") else None
        self.log(line, tag)

    def finish(self, failed, cancelled):
        self.worker = None
        self.set_busy(False)
        if cancelled:
            self.status.set("ยกเลิกแล้ว")
            self.log("ยกเลิกแล้ว (ไฟล์ .part ที่ค้างอยู่จะโหลดต่อได้เมื่อดาวน์โหลดลิงก์เดิมอีกครั้ง)", "warn")
        elif self.job_kind == "update":
            ok = not failed
            self.status.set("อัปเดต yt-dlp เรียบร้อย" if ok else "อัปเดต yt-dlp ไม่สำเร็จ")
            self.log(self.status.get(), "ok" if ok else "error")
        elif failed:
            self.status.set(f"เสร็จแล้ว แต่มี {failed} ลิงก์ที่ดาวน์โหลดไม่สำเร็จ")
            self.log(self.status.get() + " - ลองกด 'อัปเดต yt-dlp' แล้วลองใหม่", "error")
        else:
            self.progress.configure(value=100)
            self.status.set("ดาวน์โหลดเสร็จแล้ว ✓")
            self.log("ดาวน์โหลดเสร็จแล้ว", "ok")
        self.bell()

    # ---------- ปิดโปรแกรม ----------

    def save_settings(self):
        data = {"mode": self.mode.get(), "playlist": self.playlist.get(), "out_dir": self.out_dir.get().strip()}
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def on_close(self):
        if self.worker:
            if not messagebox.askyesno("กำลังดาวน์โหลด", "กำลังดาวน์โหลดอยู่ ต้องการยกเลิกและปิดโปรแกรมไหม?"):
                return
            self.worker.cancel()
        self.save_settings()
        self.destroy()


def enable_dpi_awareness():
    """ไม่ให้ตัวหนังสือเบลอบนจอที่ตั้ง scale ไว้มากกว่า 100%"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main():
    enable_dpi_awareness()
    App().mainloop()


if __name__ == "__main__":
    main()
