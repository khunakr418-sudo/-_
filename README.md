# YouTube Downloader (yt-dlp)

โปรแกรมดาวน์โหลดวิดีโอ/เสียงจาก YouTube สำหรับใช้ในเครื่องส่วนตัว (Windows) โดยใช้ [yt-dlp](https://github.com/yt-dlp/yt-dlp) และ ffmpeg

## ติดตั้ง (ครั้งแรกครั้งเดียว)

ดับเบิลคลิก **`setup.bat`**

สคริปต์จะดาวน์โหลดไฟล์จาก GitHub ทางการของ yt-dlp มาไว้ในโฟลเดอร์ `bin\` และตรวจ SHA-256 ก่อนใช้งาน:

| ไฟล์ | ที่มา | ใช้ทำอะไร |
|---|---|---|
| `yt-dlp.exe` | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp/releases) | ตัวดาวน์โหลด |
| `ffmpeg.exe`, `ffprobe.exe` | [yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds/releases) | รวมภาพ+เสียง, แปลงเป็น MP3 |

ถ้ารัน `setup.bat` ซ้ำ จะอัปเดต yt-dlp เป็นเวอร์ชันล่าสุด (ใช้ `setup.bat -Force` เพื่อโหลดใหม่ทั้งหมด)

> YouTube ต้องใช้ JavaScript runtime ด้วย — ถ้าเครื่องมี [Node.js](https://nodejs.org) หรือ [Deno](https://deno.com) อยู่แล้ว โปรแกรมจะใช้ให้อัตโนมัติ

## ใช้งาน

### แบบหน้าต่าง (GUI) — แนะนำ

ดับเบิลคลิก **`gui.bat`** (ต้องมี [Python 3](https://www.python.org/downloads/) ในเครื่อง ไม่ต้องติดตั้งแพ็กเกจเพิ่ม)

1. วางลิงก์ในช่องด้านบน (1 บรรทัดต่อ 1 ลิงก์) หรือกดปุ่ม **วางลิงก์**
2. เลือกรูปแบบ: วิดีโอคุณภาพสูงสุด / 1080p / 720p / MP3
3. เลือกโฟลเดอร์ที่จะบันทึก แล้วกด **ดาวน์โหลด** (หรือ Ctrl+Enter)

หน้าต่างจะแสดงแถบความคืบหน้า ความเร็ว และเวลาที่เหลือ กด **ยกเลิก** ได้ระหว่างโหลด
โปรแกรมจะจำรูปแบบและโฟลเดอร์ที่เลือกไว้ใช้ครั้งต่อไป (เก็บใน `gui_settings.json`)

### แบบเมนูใน console

ดับเบิลคลิก **`download.bat`** แล้วเลือกเมนู:

```
========== YouTube Downloader (yt-dlp) ==========
 1) วิดีโอ คุณภาพสูงสุด (MP4)
 2) วิดีโอ 1080p (MP4)
 3) วิดีโอ 720p (MP4)
 4) เสียงอย่างเดียว (MP3)
 5) อัปเดต yt-dlp
 6) เปิดโฟลเดอร์ที่ดาวน์โหลด
 0) ออก
```

- วางลิงก์ได้หลายลิงก์พร้อมกัน (คั่นด้วยช่องว่าง)
- ถ้าลิงก์อยู่ในเพลย์ลิสต์ โปรแกรมจะถามว่าจะโหลดทั้งเพลย์ลิสต์หรือไม่ (ทั้งเพลย์ลิสต์จะแยกเป็นโฟลเดอร์ตามชื่อเพลย์ลิสต์)
- ไฟล์จะอยู่ในโฟลเดอร์ `downloads\`

### สั่งจาก command line

```bat
download.bat -Url "https://youtu.be/xxxx"
download.bat -Url "https://youtu.be/xxxx" -Mode mp3
download.bat -Url "https://youtube.com/playlist?list=xxxx" -Mode 720 -Playlist
download.bat -Url "https://youtu.be/xxxx" -OutDir "D:\Videos"
```

`-Mode` เลือกได้: `best` (ค่าเริ่มต้น), `1080`, `720`, `mp3`

## ตั้งค่าเพิ่มเติม

แก้ไฟล์ **`yt-dlp.conf`** (เอา `#` หน้าบรรทัดออกเพื่อเปิดใช้) เช่น

- `--cookies-from-browser firefox` — ใช้เมื่อ YouTube ขึ้น *"Sign in to confirm you're not a bot"*
- `--write-subs --sub-langs th,en --embed-subs` — โหลดซับไตเติลแล้วฝังในวิดีโอ
- `--limit-rate 5M` — จำกัดความเร็ว

## แก้ปัญหา

| อาการ | วิธีแก้ |
|---|---|
| ดาวน์โหลดไม่ได้ / error แปลก ๆ | เมนู `5) อัปเดต yt-dlp` — YouTube เปลี่ยนระบบบ่อย yt-dlp ต้องอัปเดตตาม |
| ได้แค่ 360p หรือแปลง MP3 ไม่ได้ | ยังไม่มี ffmpeg — รัน `setup.bat` |
| ขึ้นว่าต้องยืนยันว่าไม่ใช่บอท | เปิด `--cookies-from-browser` ใน `yt-dlp.conf` |

## โครงสร้างโปรเจค

```
setup.bat / setup.ps1        ดาวน์โหลด/อัปเดต yt-dlp และ ffmpeg
gui.bat / gui.pyw            หน้าต่างดาวน์โหลด (GUI, Python tkinter)
download.bat / download.ps1  เมนูดาวน์โหลดแบบ console
yt-dlp.conf                  ตัวเลือกเพิ่มเติมของ yt-dlp (ใช้ทั้ง GUI และ console)
gui_settings.json            ค่าที่ GUI จำไว้ (ไม่เก็บใน git)
bin\                         yt-dlp.exe, ffmpeg.exe, ffprobe.exe (ไม่เก็บใน git)
downloads\                   ไฟล์ที่ดาวน์โหลด (ไม่เก็บใน git)
```

> โปรดดาวน์โหลดเฉพาะเนื้อหาที่คุณมีสิทธิ์ใช้งาน และปฏิบัติตามข้อกำหนดของ YouTube
