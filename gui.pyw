"""
YouTube Downloader GUI - หน้าต่างสำหรับดาวน์โหลดวิดีโอ/เสียงด้วย bin\\yt-dlp.exe

เปิดด้วย gui.bat (หรือดับเบิลคลิกไฟล์นี้) - ต้องรัน setup.bat ก่อนครั้งแรก
ใช้แค่ Python มาตรฐาน (tkinter) ไม่ต้องติดตั้งแพ็กเกจเพิ่ม
"""
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

import ytcore
from ytcore import MODES


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.events = queue.Queue()
        self.worker = None
        self.job_kind = None
        self.tracker = ytcore.ProgressTracker()

        settings = ytcore.load_settings()
        self.mode = tk.StringVar(value=settings["mode"])
        self.playlist = tk.BooleanVar(value=settings["playlist"])
        self.out_dir = tk.StringVar(value=settings["out_dir"])
        self.status = tk.StringVar(value="พร้อมดาวน์โหลด")
        self.detail = tk.StringVar()

        self._setup_fonts()
        self._build_ui()
        scale = self.tk.call("tk", "scaling") / (96 / 72)
        self.minsize(int(640 * scale), int(600 * scale))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-Return>", lambda e: self.start_download())
        self.after(100, self.poll_events)
        if not ytcore.YTDLP.exists():
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
        folder = Path(self.out_dir.get().strip() or ytcore.DEFAULT_OUT_DIR)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            messagebox.showerror("เปิดโฟลเดอร์ไม่ได้", str(e))

    def ask_setup(self):
        if messagebox.askyesno("ยังไม่ได้ติดตั้ง",
                               "ไม่พบ bin\\yt-dlp.exe\n\nเปิด setup.bat เพื่อติดตั้งตอนนี้ไหม?\n"
                               "(ติดตั้งเสร็จแล้วกดดาวน์โหลดได้เลย)"):
            os.startfile(ytcore.ROOT / "setup.bat")

    def start_download(self):
        if self.worker:
            return
        urls = self.get_urls()
        if not urls:
            messagebox.showwarning("ยังไม่มีลิงก์", "กรุณาวางลิงก์ YouTube อย่างน้อย 1 ลิงก์")
            return
        if not ytcore.YTDLP.exists():
            self.ask_setup()
            return
        out_dir = Path(self.out_dir.get().strip() or ytcore.DEFAULT_OUT_DIR)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("สร้างโฟลเดอร์ไม่ได้", str(e))
            return
        self.save_settings()

        mode = self.mode.get()
        self.log(f"=== {MODES[mode]} : {len(urls)} ลิงก์ -> {out_dir}", "info")
        if not ytcore.FFMPEG.exists():
            self.log(ytcore.FFMPEG_WARNING, "warn")
        commands = [ytcore.build_command(u, mode, out_dir, self.playlist.get()) for u in urls]
        self.run_worker("download", commands, "กำลังเริ่มดาวน์โหลด...")

    def update_ytdlp(self):
        if self.worker:
            return
        if not ytcore.YTDLP.exists():
            self.ask_setup()
            return
        self.log("=== อัปเดต yt-dlp", "info")
        self.run_worker("update", [ytcore.update_command()], "กำลังอัปเดต yt-dlp...")

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
        self.worker = ytcore.Worker(commands, self.events)
        self.worker.start()

    # ---------- รับผลจาก yt-dlp ----------

    def poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "line":
                    self.handle_line(event[1])
                elif event[0] == "job":
                    self.tracker.reset(event[1], event[2])
                elif event[0] == "done":
                    self.finish(event[1], event[2])
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    def handle_line(self, line):
        update = self.tracker.feed(line)
        if update.percent is not None:
            self.progress.configure(value=update.percent)
        if update.status is not None:
            self.status.set(update.status)
        if update.detail is not None:
            self.detail.set(update.detail)
        if update.log is not None:
            self.log(update.log, update.tag)

    def finish(self, failed, cancelled):
        self.worker = None
        self.set_busy(False)
        status, message, tag = ytcore.summary(self.job_kind, failed, cancelled)
        if tag == "ok" and self.job_kind == "download":
            self.progress.configure(value=100)
        self.status.set(status)
        self.log(message, tag)
        self.bell()

    # ---------- ปิดโปรแกรม ----------

    def save_settings(self):
        ytcore.save_settings(self.mode.get(), self.playlist.get(), self.out_dir.get())

    def on_close(self):
        if self.worker:
            if not messagebox.askyesno("กำลังดาวน์โหลด", "กำลังดาวน์โหลดอยู่ ต้องการยกเลิกและปิดโปรแกรมไหม?"):
                return
            self.worker.cancel()
        self.save_settings()
        self.destroy()


def main():
    ytcore.enable_dpi_awareness()
    App().mainloop()


if __name__ == "__main__":
    main()
