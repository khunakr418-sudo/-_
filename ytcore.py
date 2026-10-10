"""
ytcore.py - ส่วนกลางที่ gui.pyw และ web.py ใช้ร่วมกัน
สร้างคำสั่ง yt-dlp, รันในเธรดแยก, แปลงข้อความ progress เป็นสถานะสำหรับแสดงผล และจำค่าที่ผู้ใช้เลือก
"""
import json
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

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

FFMPEG_WARNING = "คำเตือน: ไม่พบ ffmpeg.exe - จะได้แค่วิดีโอความละเอียดต่ำ และแปลง MP3 ไม่ได้ (รัน setup.bat)"

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


# ---------- คำสั่ง yt-dlp ----------

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


def update_command():
    return [str(YTDLP), "-U"]


def ytdlp_version():
    try:
        out = subprocess.run([str(YTDLP), "--version"], capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ---------- รันในเธรดแยก ----------

class Worker(threading.Thread):
    """รันคำสั่ง yt-dlp ทีละคำสั่ง แล้วส่ง event กลับผ่าน events.put():
    ("job", ลำดับ, ทั้งหมด), ("line", ข้อความ), ("done", จำนวนที่ไม่สำเร็จ, ถูกยกเลิกไหม)"""

    def __init__(self, commands, events, creationflags=NO_WINDOW):
        super().__init__(daemon=True)
        self.commands = commands
        self.events = events
        self.creationflags = creationflags
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
                    encoding="utf-8", errors="replace", bufsize=1, creationflags=self.creationflags)
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


# ---------- แปลงข้อความจาก yt-dlp เป็นสถานะ ----------

@dataclass
class Update:
    """สิ่งที่ต้องเปลี่ยนบนหน้าจอ - ค่าที่เป็น None แปลว่าไม่ต้องเปลี่ยน"""
    status: str = None
    percent: float = None
    detail: str = None
    log: str = None
    tag: str = None


class ProgressTracker:
    def __init__(self):
        self.reset()

    def reset(self, job=0, jobs=0):
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

    def feed(self, line):
        if line.startswith(PROGRESS_TAG):
            percent, speed, eta, title = (line[len(PROGRESS_TAG):].split("|", 3) + [""] * 4)[:4]
            m = PERCENT_RE.search(percent)
            eta = eta.strip()
            info = [percent.strip(), speed.strip()]
            if eta and eta != "NA":
                info.append(f"เหลือ {eta}")
            position = self.position_text()
            return Update(status=f"กำลังดาวน์โหลด: {title.strip()}",
                          percent=float(m.group(1)) if m else None,
                          detail="   ·   ".join(([position] if position else []) + info))

        update = Update(log=line)
        if line.startswith("ERROR"):
            update.tag = "error"
        elif line.startswith("WARNING"):
            update.tag = "warn"

        if m := ITEM_RE.match(line):
            self.item, self.items = int(m.group(1)), int(m.group(2))
        elif m := FORMATS_RE.match(line):
            self.part, self.parts = 0, m.group(1).count("+") + 1
        elif line.startswith("[download] Destination:"):
            self.part += 1
        elif line.startswith("Deleting original file"):
            return Update()  # ไฟล์ชั่วคราวหลังรวมภาพ+เสียง ไม่ต้องแสดง
        else:
            for prefix, text in STAGES.items():
                if line.startswith(prefix):
                    update.status = text
                    break
        return update


def summary(kind, failed, cancelled):
    """ข้อความเมื่องานจบ -> (สถานะ, ข้อความใน log, tag)"""
    if cancelled:
        return "ยกเลิกแล้ว", "ยกเลิกแล้ว (ไฟล์ .part ที่ค้างอยู่จะโหลดต่อได้เมื่อดาวน์โหลดลิงก์เดิมอีกครั้ง)", "warn"
    if kind == "update":
        status = "อัปเดต yt-dlp ไม่สำเร็จ" if failed else "อัปเดต yt-dlp เรียบร้อย"
        return status, status, "error" if failed else "ok"
    if failed:
        status = f"เสร็จแล้ว แต่มี {failed} ลิงก์ที่ดาวน์โหลดไม่สำเร็จ"
        return status, status + " - ลองกด 'อัปเดต yt-dlp' แล้วลองใหม่", "error"
    return "ดาวน์โหลดเสร็จแล้ว ✓", "ดาวน์โหลดเสร็จแล้ว", "ok"


# ---------- ค่าที่ผู้ใช้เลือก ----------

def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    mode = data.get("mode")
    return {
        "mode": mode if mode in MODES else "best",
        "playlist": bool(data.get("playlist", False)),
        "out_dir": data.get("out_dir") or str(DEFAULT_OUT_DIR),
    }


def save_settings(mode, playlist, out_dir):
    data = {"mode": mode, "playlist": playlist, "out_dir": str(out_dir).strip()}
    try:
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def enable_dpi_awareness():
    """ไม่ให้ตัวหนังสือ/หน้าต่างเลือกโฟลเดอร์เบลอบนจอที่ตั้ง scale ไว้มากกว่า 100%"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
