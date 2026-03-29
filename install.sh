#!/usr/bin/env bash
set -euo pipefail

# skill-cli installer
# Usage: curl -fsSL https://raw.githubusercontent.com/lanyun1103/skill-cli/main/install.sh | bash

INSTALL_DIR="${HOME}/.skill-cli"
BIN_DIR="${HOME}/.local/bin"
REPO_URL="https://github.com/lanyun1103/skill-cli.git"

echo "📦 Installing skill-cli..."

# 检测 OS
OS="$(uname -s)"
case "$OS" in
    Linux*)  OS_NAME="Linux" ;;
    Darwin*) OS_NAME="macOS" ;;
    MINGW*|MSYS*|CYGWIN*) OS_NAME="Windows" ;;
    *)       echo "❌ Unsupported OS: $OS"; exit 1 ;;
esac
echo "  OS: $OS_NAME"

# 检测 Python
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "❌ Python 3.10+ is required but not found."
    echo "   Install it from https://www.python.org/downloads/"
    exit 1
fi

PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "❌ Python 3.10+ required, found $PY_VER"
    exit 1
fi
echo "  Python: $PY_VER"

# 检测 git
if ! command -v git &>/dev/null; then
    echo "❌ git is required but not found."
    exit 1
fi

# 克隆或更新
if [ -d "$INSTALL_DIR/repo" ]; then
    echo "  🔄 Updating existing installation..."
    git -C "$INSTALL_DIR/repo" pull --ff-only -q
else
    echo "  📥 Cloning repository..."
    mkdir -p "$INSTALL_DIR"
    git clone -q "$REPO_URL" "$INSTALL_DIR/repo"
fi

# 创建 venv 并安装
echo "  🔧 Setting up virtual environment..."
$PYTHON -m venv "$INSTALL_DIR/venv"

if [ "$OS_NAME" = "Windows" ]; then
    PIP="$INSTALL_DIR/venv/Scripts/pip"
    VENV_BIN="$INSTALL_DIR/venv/Scripts"
else
    PIP="$INSTALL_DIR/venv/bin/pip"
    VENV_BIN="$INSTALL_DIR/venv/bin"
fi

"$PIP" install -q "$INSTALL_DIR/repo"

# 创建 bin 目录和 wrapper 脚本
mkdir -p "$BIN_DIR"

if [ "$OS_NAME" = "Windows" ]; then
    # Windows batch file
    cat > "$BIN_DIR/skill-cli.cmd" << 'BATCH'
@echo off
"%USERPROFILE%\.skill-cli\venv\Scripts\skill-cli.exe" %*
BATCH
    echo "  ✅ Created $BIN_DIR/skill-cli.cmd"
else
    # Unix wrapper
    cat > "$BIN_DIR/skill-cli" << WRAPPER
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/skill-cli" "\$@"
WRAPPER
    chmod +x "$BIN_DIR/skill-cli"
fi

# 检查 PATH
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
    echo ""
    echo "  ⚠️  $BIN_DIR is not in your PATH."
    echo "  Add it by running:"
    echo ""

    SHELL_NAME="$(basename "${SHELL:-/bin/bash}")"
    case "$SHELL_NAME" in
        zsh)  RC="~/.zshrc" ;;
        fish) RC="~/.config/fish/config.fish" ;;
        *)    RC="~/.bashrc" ;;
    esac

    if [ "$SHELL_NAME" = "fish" ]; then
        echo "    fish_add_path $BIN_DIR"
    else
        echo "    echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> $RC"
        echo "    source $RC"
    fi
    echo ""
fi

echo ""
echo "✅ skill-cli installed successfully!"
echo ""
echo "Usage:"
echo "  skill-cli add <git-url>              Add a skill repository"
echo "  skill-cli list                       List all groups"
echo "  skill-cli install <source> <group>   Install a skill group to project"
echo "  skill-cli install <source> <group> -g  Install globally"
echo "  skill-cli status                     Show install status"
echo "  skill-cli update                     Update all sources"
echo ""
