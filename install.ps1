# skill-cli installer for Windows PowerShell
# Usage: irm https://raw.githubusercontent.com/lanyun1103/skill-cli/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

$INSTALL_DIR = "$env:USERPROFILE\.skill-cli"
$BIN_DIR = "$env:USERPROFILE\.local\bin"
$REPO_URL = "https://github.com/lanyun1103/skill-cli.git"

Write-Host "📦 Installing skill-cli..." -ForegroundColor Cyan

# 检测 Python
$python = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $major, $minor = $ver.Split(".")
            if ([int]$major -ge 3 -and [int]$minor -ge 10) {
                $python = $cmd
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host "❌ Python 3.10+ is required. Install from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "  Python: $ver"

# 检测 git
try { git --version | Out-Null } catch {
    Write-Host "❌ git is required. Install from https://git-scm.com/" -ForegroundColor Red
    exit 1
}

# 克隆或更新
if (Test-Path "$INSTALL_DIR\repo") {
    Write-Host "  🔄 Updating..."
    git -C "$INSTALL_DIR\repo" pull --ff-only -q
} else {
    Write-Host "  📥 Cloning..."
    New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
    git clone -q $REPO_URL "$INSTALL_DIR\repo"
}

# venv + install
Write-Host "  🔧 Setting up..."
& $python -m venv "$INSTALL_DIR\venv"
& "$INSTALL_DIR\venv\Scripts\pip" install -q "$INSTALL_DIR\repo"

# Wrapper script
New-Item -ItemType Directory -Path $BIN_DIR -Force | Out-Null

@"
@echo off
"%USERPROFILE%\.skill-cli\venv\Scripts\skill-cli.exe" %*
"@ | Set-Content "$BIN_DIR\skill-cli.cmd" -Encoding ASCII

# 检查 PATH
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$BIN_DIR*") {
    [Environment]::SetEnvironmentVariable("PATH", "$BIN_DIR;$userPath", "User")
    Write-Host "  ✅ Added $BIN_DIR to user PATH (restart terminal to take effect)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✅ skill-cli installed!" -ForegroundColor Green
Write-Host ""
Write-Host "Usage:"
Write-Host "  skill-cli add <git-url>              Add a skill repository"
Write-Host "  skill-cli list                       List all groups"
Write-Host "  skill-cli install <source> <group>   Install to project"
Write-Host "  skill-cli install <source> <group> -g  Install globally"
Write-Host "  skill-cli status                     Show status"
Write-Host ""
