"""
web.py - หน้าเว็บสำหรับดาวน์โหลดวิดีโอ/เสียงจาก YouTube ด้วย bin\\yt-dlp.exe

เปิดด้วย web.bat แล้วเบราว์เซอร์จะเปิด http://127.0.0.1:8765 ให้อัตโนมัติ
เซิร์ฟเวอร์รับเฉพาะการเชื่อมต่อจากเครื่องนี้ - ปิดหน้าต่าง console (หรือกด Ctrl+C) เพื่อหยุด
ใช้แค่ Python มาตรฐาน ไม่ต้องติดตั้งแพ็กเกจเพิ่ม

    python web.py [--no-browser]
"""
import json
import os
import sys
import threading
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ytcore

HOST = "127.0.0.1"
PORT = 8765
APP_ID = "youtube-downloader"
INDEX_HTML = ytcore.ROOT / "web" / "index.html"
MAX_LOG = 1000
MAX_BODY = 64 * 1024


class State:
    """สถานะงานปัจจุบัน - Worker ส่ง event เข้ามาทาง put() ส่วนหน้าเว็บอ่านผ่าน /api/status"""

    def __init__(self):
        self.lock = threading.Lock()
        self.worker = None
        self.kind = None
        self.tracker = ytcore.ProgressTracker()
        self.status = "พร้อมดาวน์โหลด"
        self.percent = 0.0
        self.detail = ""
        self.result = None  # "ok" / "error" / "warn" เมื่องานล่าสุดจบ
        self.log = []
        self.seq = 0
        self.version_stale = False

    def _add_log(self, text, tag=None):
        self.seq += 1
        self.log.append({"id": self.seq, "text": text, "tag": tag})
        del self.log[:-MAX_LOG]

    def put(self, event):
        with self.lock:
            if event[0] == "line":
                update = self.tracker.feed(event[1])
                if update.percent is not None:
                    self.percent = update.percent
                if update.status is not None:
                    self.status = update.status
                if update.detail is not None:
                    self.detail = update.detail
                if update.log is not None:
                    self._add_log(update.log, update.tag)
            elif event[0] == "job":
                self.tracker.reset(event[1], event[2])
            elif event[0] == "done":
                self.status, message, tag = ytcore.summary(self.kind, event[1], event[2])
                self.result = tag
                if tag == "ok" and self.kind == "download":
                    self.percent = 100.0
                self._add_log(message, tag)
                self.version_stale = self.version_stale or self.kind == "update"
                self.worker = None

    def start(self, kind, commands, status, messages):
        with self.lock:
            if self.worker:
                return False
            self.kind, self.status, self.percent, self.detail, self.result = kind, status, 0.0, "", None
            for text, tag in messages:
                self._add_log(text, tag)
            # ไม่ใช้ CREATE_NO_WINDOW: ให้ yt-dlp/ffmpeg อยู่ใน console เดียวกัน ปิดหน้าต่างแล้วจะหยุดตามไปด้วย
            self.worker = ytcore.Worker(commands, self, creationflags=0)
            self.worker.start()
            return True

    def cancel(self):
        with self.lock:
            worker = self.worker
            if worker:
                self.status = "กำลังยกเลิก..."
        if worker:
            worker.cancel()
        return worker is not None

    def snapshot(self, since):
        with self.lock:
            return {
                "busy": self.worker is not None,
                "kind": self.kind,
                "status": self.status,
                "percent": self.percent,
                "detail": self.detail,
                "result": self.result,
                "log": [entry for entry in self.log if entry["id"] > since],
            }


STATE = State()
FOLDER_DIALOG_LOCK = threading.Lock()


def choose_folder(initial):
    """เปิดหน้าต่างเลือกโฟลเดอร์ของ Windows (เบราว์เซอร์บอก path เต็มของโฟลเดอร์ไม่ได้)"""
    import tkinter as tk
    from tkinter import filedialog

    with FOLDER_DIALOG_LOCK:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            folder = filedialog.askdirectory(parent=root, initialdir=initial or None,
                                             title="เลือกโฟลเดอร์ที่จะบันทึก")
        finally:
            root.destroy()
    return str(Path(folder)) if folder else None


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "YouTubeDownloader/1.0"

    def log_message(self, fmt, *args):
        pass  # ไม่ต้องพิมพ์ทุก request ลง console

    # ---------- ความปลอดภัย ----------
    # รับเฉพาะ request ที่มาจากหน้าเว็บนี้เอง: ตรวจ Host (กัน DNS rebinding) และ Origin (กันเว็บอื่นสั่งดาวน์โหลด)

    def _check_request(self, post):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            raise ApiError(HTTPStatus.FORBIDDEN, "host not allowed")
        if post:
            origin = self.headers.get("Origin")
            if origin and origin not in self.server.allowed_origins:
                raise ApiError(HTTPStatus.FORBIDDEN, "origin not allowed")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "ต้องส่งเป็น application/json")

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=HTTPStatus.OK):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "ข้อมูลใหญ่เกินไป")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON ไม่ถูกต้อง")
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON ไม่ถูกต้อง")
        return data

    def _handle(self, post):
        try:
            self._check_request(post)
            url = urlparse(self.path)
            routes = POST_ROUTES if post else GET_ROUTES
            route = routes.get(url.path)
            if not route:
                raise ApiError(HTTPStatus.NOT_FOUND, "not found")
            route(self, self._read_json() if post else parse_qs(url.query))
        except ApiError as e:
            self._send_json({"error": str(e)}, e.status)
        except Exception as e:  # noqa: BLE001 - ตอบ error กลับไปให้หน้าเว็บแสดง แทนการตัดการเชื่อมต่อเฉย ๆ
            self._send_json({"error": f"เกิดข้อผิดพลาด: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self):
        self._handle(post=False)

    def do_POST(self):
        self._handle(post=True)

    # ---------- GET ----------

    def get_index(self, query):
        self._send(HTTPStatus.OK, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")

    def get_info(self, query):
        if STATE.version_stale:  # หลังอัปเดต yt-dlp ให้อ่านเวอร์ชันใหม่
            STATE.version_stale = False
            self.server.ytdlp_version = ytcore.ytdlp_version()
        self._send_json({
            "app": APP_ID,
            # ส่งเป็น list เพื่อคงลำดับ (object ใน JavaScript จะเรียงคีย์ที่เป็นตัวเลขอย่าง "720" ขึ้นก่อน)
            "modes": [{"id": key, "label": label} for key, label in ytcore.MODES.items()],
            "settings": ytcore.load_settings(),
            "ytdlp": self.server.ytdlp_version if ytcore.YTDLP.exists() else None,
            "ffmpeg": ytcore.FFMPEG.exists(),
        })

    def get_status(self, query):
        try:
            since = int(query.get("since", ["0"])[0])
        except ValueError:
            since = 0
        self._send_json(STATE.snapshot(since))

    # ---------- POST ----------

    def post_download(self, data):
        urls = data.get("urls")
        if isinstance(urls, str):
            urls = urls.split()
        if not isinstance(urls, list):
            urls = []
        urls = [str(u).strip().strip("\"'") for u in urls if str(u).strip().strip("\"'")]
        if not urls:
            raise ApiError(HTTPStatus.BAD_REQUEST, "กรุณาวางลิงก์ YouTube อย่างน้อย 1 ลิงก์")
        bad = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
        if bad:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"ลิงก์ไม่ถูกต้อง: {bad[0]}")
        mode = data.get("mode")
        if mode not in ytcore.MODES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "รูปแบบไม่ถูกต้อง")
        if not ytcore.YTDLP.exists():
            raise ApiError(HTTPStatus.CONFLICT, "ไม่พบ bin\\yt-dlp.exe - กรุณารัน setup.bat ก่อน")
        playlist = bool(data.get("playlist"))
        out_dir = Path(str(data.get("out_dir") or "").strip() or ytcore.DEFAULT_OUT_DIR)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"สร้างโฟลเดอร์ไม่ได้: {e}")
        ytcore.save_settings(mode, playlist, out_dir)

        messages = [(f"=== {ytcore.MODES[mode]} : {len(urls)} ลิงก์ -> {out_dir}", "info")]
        if not ytcore.FFMPEG.exists():
            messages.append((ytcore.FFMPEG_WARNING, "warn"))
        commands = [ytcore.build_command(u, mode, out_dir, playlist) for u in urls]
        if not STATE.start("download", commands, "กำลังเริ่มดาวน์โหลด...", messages):
            raise ApiError(HTTPStatus.CONFLICT, "กำลังดาวน์โหลดอยู่ - รอให้เสร็จก่อน")
        self._send_json({"ok": True})

    def post_update(self, data):
        if not ytcore.YTDLP.exists():
            raise ApiError(HTTPStatus.CONFLICT, "ไม่พบ bin\\yt-dlp.exe - กรุณารัน setup.bat ก่อน")
        if not STATE.start("update", [ytcore.update_command()], "กำลังอัปเดต yt-dlp...",
                           [("=== อัปเดต yt-dlp", "info")]):
            raise ApiError(HTTPStatus.CONFLICT, "กำลังทำงานอยู่ - รอให้เสร็จก่อน")
        self._send_json({"ok": True})

    def post_cancel(self, data):
        self._send_json({"ok": STATE.cancel()})

    def post_open_folder(self, data):
        folder = Path(str(data.get("out_dir") or "").strip() or ytcore.DEFAULT_OUT_DIR)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"เปิดโฟลเดอร์ไม่ได้: {e}")
        if not folder.is_dir():  # os.startfile เปิดได้ทุกอย่าง - อนุญาตเฉพาะโฟลเดอร์
            raise ApiError(HTTPStatus.BAD_REQUEST, "ไม่ใช่โฟลเดอร์")
        os.startfile(folder)
        self._send_json({"ok": True})

    def post_choose_folder(self, data):
        self._send_json({"path": choose_folder(str(data.get("initial") or ""))})


GET_ROUTES = {
    "/": Handler.get_index,
    "/index.html": Handler.get_index,
    "/api/info": Handler.get_info,
    "/api/status": Handler.get_status,
}
POST_ROUTES = {
    "/api/download": Handler.post_download,
    "/api/update": Handler.post_update,
    "/api/cancel": Handler.post_cancel,
    "/api/open-folder": Handler.post_open_folder,
    "/api/choose-folder": Handler.post_choose_folder,
}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # บน Windows ถ้าเปิดไว้จะ bind พอร์ตซ้ำกับโปรแกรมอื่นได้

    def __init__(self, port):
        super().__init__((HOST, port), Handler)
        self.allowed_hosts = {f"{HOST}:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self.ytdlp_version = ytcore.ytdlp_version() if ytcore.YTDLP.exists() else None


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/info", timeout=1) as r:
            return json.load(r).get("app") == APP_ID
    except (OSError, ValueError):
        return False


def main():
    open_browser = "--no-browser" not in sys.argv[1:]
    ytcore.enable_dpi_awareness()

    if already_running(PORT):
        print(f"YouTube Downloader เปิดอยู่แล้วที่ http://{HOST}:{PORT}/")
        if open_browser:
            webbrowser.open(f"http://{HOST}:{PORT}/")
        return

    server = None
    for port in range(PORT, PORT + 20):
        try:
            server = Server(port)
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"ไม่มีพอร์ตว่างระหว่าง {PORT}-{PORT + 19}")

    url = f"http://{HOST}:{server.server_address[1]}/"
    print("=" * 56)
    print(" YouTube Downloader (web)")
    print(f" เปิดเบราว์เซอร์ที่: {url}")
    print(" ปิดหน้าต่างนี้ หรือกด Ctrl+C เพื่อหยุดเซิร์ฟเวอร์")
    print("=" * 56, flush=True)
    if not ytcore.YTDLP.exists():
        print("คำเตือน: ไม่พบ bin\\yt-dlp.exe - กรุณารัน setup.bat ก่อน", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STATE.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
