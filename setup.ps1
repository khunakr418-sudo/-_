<#
  setup.ps1 - ดาวน์โหลด yt-dlp.exe และ ffmpeg มาไว้ในโฟลเดอร์ bin\
  ทุกไฟล์ดาวน์โหลดจาก GitHub ทางการของ yt-dlp และตรวจ SHA-256 ก่อนใช้งาน

  ใช้งาน:
    setup.bat                 ติดตั้ง / อัปเดตทั้งหมด
    setup.bat -SkipFfmpeg     ไม่ติดตั้ง ffmpeg (จะโหลดได้แค่ไฟล์ที่ไม่ต้องรวมภาพ+เสียง และแปลง MP3 ไม่ได้)
    setup.bat -Force          ดาวน์โหลดใหม่ทั้งหมดแม้มีอยู่แล้ว
#>
param(
    [switch]$SkipFfmpeg,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$BinDir = Join-Path $PSScriptRoot 'bin'
$TmpDir = Join-Path $BinDir '.tmp'
New-Item -ItemType Directory -Force -Path $BinDir, $TmpDir | Out-Null

$YtDlpBase  = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download'
$FfmpegBase = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest'
$FfmpegZip  = 'ffmpeg-master-latest-win64-gpl.zip'

function Save-Url([string]$Url, [string]$Dest) {
    Write-Host "    $Url" -ForegroundColor DarkGray
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -fL --retry 3 --progress-bar -o $Dest $Url
        if ($LASTEXITCODE -ne 0) { throw "ดาวน์โหลดไม่สำเร็จ: $Url" }
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
    }
}

# ตรวจ SHA-256 ของไฟล์ เทียบกับไฟล์ checksum (รูปแบบ "<hash>  <ชื่อไฟล์>")
function Assert-Sha256([string]$File, [string]$SumsFile, [string]$Name) {
    $pattern = "^\s*([0-9a-fA-F]{64})\s+\*?$([regex]::Escape($Name))\s*$"
    $m = Get-Content $SumsFile | ForEach-Object { [regex]::Match($_, $pattern) } | Where-Object Success | Select-Object -First 1
    if (-not $m) { throw "ไม่พบ checksum ของ $Name" }
    $expected = $m.Groups[1].Value.ToLower()
    $actual = (Get-FileHash $File -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { throw "SHA-256 ของ $Name ไม่ตรง! (คาดว่า $expected ได้ $actual)" }
    Write-Host "    SHA-256 ถูกต้อง" -ForegroundColor DarkGreen
}

try {
    # ---------- yt-dlp ----------
    $YtDlp = Join-Path $BinDir 'yt-dlp.exe'
    if ((Test-Path $YtDlp) -and -not $Force) {
        Write-Host "[yt-dlp] มีอยู่แล้ว - ตรวจหาอัปเดต..." -ForegroundColor Cyan
        & $YtDlp -U
    } else {
        Write-Host "[yt-dlp] กำลังดาวน์โหลด..." -ForegroundColor Cyan
        $part = Join-Path $TmpDir 'yt-dlp.exe'
        $sums = Join-Path $TmpDir 'SHA2-256SUMS'
        Save-Url "$YtDlpBase/yt-dlp.exe" $part
        Save-Url "$YtDlpBase/SHA2-256SUMS" $sums
        Assert-Sha256 $part $sums 'yt-dlp.exe'
        Move-Item $part $YtDlp -Force
    }
    Write-Host "    เวอร์ชัน: $(& $YtDlp --version)"

    # ---------- ffmpeg ----------
    $Ffmpeg = Join-Path $BinDir 'ffmpeg.exe'
    if ($SkipFfmpeg) {
        Write-Host "[ffmpeg] ข้าม (-SkipFfmpeg)" -ForegroundColor Yellow
    } elseif ((Test-Path $Ffmpeg) -and -not $Force) {
        Write-Host "[ffmpeg] มีอยู่แล้ว (ใช้ -Force เพื่อโหลดใหม่)" -ForegroundColor Cyan
    } else {
        Write-Host "[ffmpeg] กำลังดาวน์โหลด (ประมาณ 150 MB)..." -ForegroundColor Cyan
        $zip  = Join-Path $TmpDir $FfmpegZip
        $sums = Join-Path $TmpDir 'checksums.sha256'
        Save-Url "$FfmpegBase/$FfmpegZip" $zip
        Save-Url "$FfmpegBase/checksums.sha256" $sums
        Assert-Sha256 $zip $sums $FfmpegZip

        Write-Host "    กำลังแตกไฟล์ ffmpeg.exe / ffprobe.exe..."
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            $entries = $archive.Entries | Where-Object { $_.FullName -match '/bin/(ffmpeg|ffprobe)\.exe$' }
            if (@($entries).Count -lt 2) { throw "ไม่พบ ffmpeg.exe / ffprobe.exe ใน $FfmpegZip" }
            foreach ($e in $entries) {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $BinDir $e.Name), $true)
            }
        } finally {
            $archive.Dispose()
        }
    }
    if (Test-Path $Ffmpeg) {
        Write-Host "    $((& $Ffmpeg -hide_banner -version | Select-Object -First 1))"
    }

    Write-Host ""
    Write-Host "ติดตั้งเสร็จแล้ว! ดับเบิลคลิก download.bat เพื่อเริ่มดาวน์โหลด" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "เกิดข้อผิดพลาด: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Remove-Item $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
