# One command = one video, locally on Windows.
# - downloads rhubarb (Windows build) into tools\rhubarb on first run
# - then runs the full pipeline: topic -> script -> edge-tts -> rhubarb -> hyperframes render
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$rhubarb = Join-Path $root "tools\rhubarb\rhubarb.exe"
if (-not (Test-Path $rhubarb)) {
  Write-Host "[run_local] downloading rhubarb-lip-sync v1.14.0 (Windows)..."
  New-Item -ItemType Directory -Force -Path (Join-Path $root "tools\rhubarb") | Out-Null
  $zip = Join-Path $env:TEMP "rhubarb.zip"
  Invoke-WebRequest -Uri "https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Windows.zip" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath (Join-Path $env:TEMP "rhubarb") -Force
  $exe = Get-ChildItem (Join-Path $env:TEMP "rhubarb") -Recurse -Filter "rhubarb.exe" | Select-Object -First 1
  Copy-Item $exe.FullName $rhubarb
  # rhubarb needs its resource folder (sphinx dict etc.) next to the exe
  $res = Join-Path $exe.Directory.FullName "res"
  if (Test-Path $res) { Copy-Item $res (Join-Path $root "tools\rhubarb\res") -Recurse -Force }
  Write-Host "[run_local] rhubarb ready: $rhubarb"
}
$env:RHUBARB_BIN = $rhubarb
python "pipeline\make_video.py" @args
