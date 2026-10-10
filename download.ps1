<#
  download.ps1 - ดาวน์โหลดวิดีโอ/เสียงจาก YouTube ด้วย yt-dlp.exe

  แบบเมนู (ดับเบิลคลิก download.bat):
    download.bat

  แบบสั่งตรง:
    download.bat -Url "https://youtu.be/xxxx"                    วิดีโอคุณภาพสูงสุด
    download.bat -Url "https://youtu.be/xxxx" -Mode mp3          เสียง MP3
    download.bat -Url "URL1","URL2" -Mode 720 -Playlist           720p, โหลดทั้งเพลย์ลิสต์
    download.bat -Url "https://youtu.be/xxxx" -OutDir "D:\Videos"
#>
param(
    [string[]]$Url,
    [ValidateSet('best', '1080', '720', 'mp3')]
    [string]$Mode = 'best',
    [string]$OutDir = (Join-Path $PSScriptRoot 'downloads'),
    [switch]$Playlist
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Console]::InputEncoding = [Text.Encoding]::UTF8

$BinDir = Join-Path $PSScriptRoot 'bin'
$YtDlp  = Join-Path $BinDir 'yt-dlp.exe'
$Config = Join-Path $PSScriptRoot 'yt-dlp.conf'

$Modes = [ordered]@{
    'best' = 'วิดีโอ คุณภาพสูงสุด (MP4)'
    '1080' = 'วิดีโอ 1080p (MP4)'
    '720'  = 'วิดีโอ 720p (MP4)'
    'mp3'  = 'เสียงอย่างเดียว (MP3)'
}

function Get-FormatArgs([string]$Mode) {
    switch ($Mode) {
        'mp3'   { return @('-f', 'ba/b', '-x', '--audio-format', 'mp3', '--audio-quality', '0', '--embed-thumbnail') }
        'best'  { $sort = 'res,ext:mp4:m4a' }
        default { $sort = "res:$Mode,ext:mp4:m4a" }
    }
    return @('-f', 'bv*+ba/b', '-S', $sort, '--merge-output-format', 'mp4')
}

function Test-PlaylistUrl([string]$u) { return $u -match '[?&]list=' }

function Invoke-Download([string[]]$Urls, [string]$Mode, [bool]$AllowPlaylist) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

    if ($AllowPlaylist) {
        $template = '%(playlist_title,playlist_id)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s'
    } else {
        $template = '%(title)s [%(id)s].%(ext)s'
    }

    $ytArgs = @(
        '--ffmpeg-location', $BinDir
        '-P', $OutDir
        '-o', $template
        '--embed-metadata'
        '--no-mtime'
        '--progress'
    )
    if (-not $AllowPlaylist) { $ytArgs += '--no-playlist' }
    # YouTube ต้องใช้ JavaScript runtime - ถ้ามี Node.js ในเครื่องก็ใช้ (Deno ใช้ได้อัตโนมัติอยู่แล้ว)
    if (Get-Command node -ErrorAction SilentlyContinue) { $ytArgs += @('--js-runtimes', 'node') }
    if (Test-Path $Config) { $ytArgs += @('--config-locations', $Config) }
    $ytArgs += Get-FormatArgs $Mode
    $ytArgs += '--'
    $ytArgs += $Urls

    Write-Host ""
    Write-Host ">> $($Modes[$Mode])  ->  $OutDir" -ForegroundColor Cyan
    # เรียกตรง ๆ (ไม่ capture output) เพื่อให้ progress bar ของ yt-dlp แสดงผลสด
    & $YtDlp @ytArgs
    $code = $script:DownloadExitCode = $LASTEXITCODE
    if ($code -eq 0) {
        Write-Host "ดาวน์โหลดเสร็จแล้ว" -ForegroundColor Green
    } else {
        Write-Host "มีบางรายการดาวน์โหลดไม่สำเร็จ (exit code $code) - ลองเลือก 5) อัปเดต yt-dlp แล้วลองใหม่" -ForegroundColor Red
    }
}

function Read-Urls {
    $line = Read-Host "วางลิงก์ YouTube (หลายลิงก์คั่นด้วยช่องว่าง, Enter ว่าง = กลับเมนู)"
    return @($line -split '\s+' | ForEach-Object { $_.Trim('"', "'") } | Where-Object { $_ })
}

# ---------------------------------------------------------------------------

if (-not (Test-Path $YtDlp)) {
    Write-Host "ไม่พบ bin\yt-dlp.exe - กรุณารัน setup.bat ก่อน" -ForegroundColor Red
    if (-not $Url) { Read-Host "กด Enter เพื่อปิด" | Out-Null }
    exit 1
}
if (-not (Test-Path (Join-Path $BinDir 'ffmpeg.exe'))) {
    Write-Host "คำเตือน: ไม่พบ ffmpeg.exe - จะได้แค่วิดีโอความละเอียดต่ำ และแปลง MP3 ไม่ได้ (รัน setup.bat เพื่อติดตั้ง)" -ForegroundColor Yellow
}

# โหมดสั่งตรง: มี -Url มาแล้วก็ดาวน์โหลดเลย
if ($Url) {
    $urls = @($Url | ForEach-Object { $_ -split '[,\s]+' } | Where-Object { $_ })
    Invoke-Download $urls $Mode ([bool]$Playlist)
    exit $script:DownloadExitCode
}

# โหมดเมนู
while ($true) {
    Write-Host ""
    Write-Host "========== YouTube Downloader (yt-dlp) ==========" -ForegroundColor Magenta
    $i = 1
    foreach ($m in $Modes.Values) { Write-Host " $i) $m"; $i++ }
    Write-Host " 5) อัปเดต yt-dlp"
    Write-Host " 6) เปิดโฟลเดอร์ที่ดาวน์โหลด"
    Write-Host " 0) ออก"
    $choice = (Read-Host "เลือก").Trim()

    switch ($choice) {
        { $_ -in '1', '2', '3', '4' } {
            $mode = @($Modes.Keys)[[int]$choice - 1]
            $urls = Read-Urls
            if (-not $urls) { break }

            $allowPlaylist = $false
            if ($urls | Where-Object { Test-PlaylistUrl $_ }) {
                $ans = Read-Host "ลิงก์นี้อยู่ในเพลย์ลิสต์ - ดาวน์โหลดทั้งเพลย์ลิสต์ไหม? (y/N)"
                $allowPlaylist = $ans -match '^(y|yes|ใช่)$'
            }
            Invoke-Download $urls $mode $allowPlaylist
        }
        '5' { & $YtDlp -U }
        '6' {
            New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
            Invoke-Item $OutDir
        }
        '0' { exit 0 }
        default { Write-Host "กรุณาเลือก 0-6" -ForegroundColor Yellow }
    }
}
