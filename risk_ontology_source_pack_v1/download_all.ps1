$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" download_all.py --manifest material_manifest.csv --output downloaded_sources

Write-Host "下载完成。请查看 downloaded_sources\download_log.csv"
