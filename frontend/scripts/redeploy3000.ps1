# Safe redeploy of the production UI on :3000.
# Why: `next build` replaces .next/static chunk files.  A server that was started BEFORE the build
# keeps serving the old build manifest -> 500 on missing chunk hashes -> "Application error: a client-side
# exception has occurred".  So: build, restart that exact server PID, then smoke-test every page.
param([string]$RunScript = "C:\Users\borah\run_server3000.ps1")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
npx next build
if ($LASTEXITCODE -ne 0) { throw "next build failed; server left untouched" }
$pid3000 = (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($pid3000) { taskkill /PID $pid3000 /T /F | Out-Null; Start-Sleep 2 }   # exact PID only; never ingest processes
Start-Process powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",$RunScript -WindowStyle Hidden | Out-Null
Start-Sleep 12
node scripts\smoke_pages.cjs
exit $LASTEXITCODE
