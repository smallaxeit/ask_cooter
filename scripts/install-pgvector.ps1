# Installs the locally-built pgvector 0.8.6 into PostgreSQL 18.
# Copies three files into C:\Program Files\PostgreSQL\18 (admin required).
# Self-elevates via UAC if not already running as Administrator.
#
#   Right-click > Run with PowerShell, or:
#   powershell -ExecutionPolicy Bypass -File scripts\install-pgvector.ps1

$ErrorActionPreference = 'Stop'

# --- self-elevate ---
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent() `
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Elevating (UAC prompt)..."
    Start-Process powershell -Verb RunAs -ArgumentList `
        "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$PgRoot   = 'C:\Program Files\PostgreSQL\18'
$BuildDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'pgvector-build'

$libDir = Join-Path $PgRoot 'lib'
$extDir = Join-Path $PgRoot 'share\extension'

if (-not (Test-Path $PgRoot)) { throw "PostgreSQL 17 not found at $PgRoot" }
if (-not (Test-Path $BuildDir)) { throw "Build artifacts not found at $BuildDir" }

Copy-Item (Join-Path $BuildDir 'vector.dll')     $libDir -Force
Copy-Item (Join-Path $BuildDir 'vector.control') $extDir -Force
Copy-Item (Join-Path $BuildDir 'vector--*.sql')  $extDir -Force

Write-Host "pgvector installed into $PgRoot"
Write-Host "  lib\vector.dll"
Write-Host "  share\extension\vector.control"
Write-Host "  share\extension\vector--*.sql"
Write-Host ""
Write-Host "Next: create the database (see scripts\bootstrap-db.sql)."
Read-Host "Press Enter to close"
