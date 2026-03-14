#!/usr/bin/env bash
# ============================================================
# ESP32 Voice Assistant — PC Backend Setup Script
# ============================================================
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================="
echo "  ESP32 Voice Assistant — Backend Setup"
echo "============================================="
echo ""

# ── 1. Python virtual environment ──────────────────────
echo "[1/5] Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  ✓ Created venv"
else
    echo "  ✓ venv already exists"
fi

source venv/bin/activate
echo "  ✓ Activated venv ($(python --version))"

# ── 2. Install Python dependencies ─────────────────────
echo ""
echo "[2/5] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✓ Dependencies installed"

# ── 3. Download Piper TTS model ────────────────────────
echo ""
echo "[3/5] Downloading Piper TTS voice model..."
mkdir -p models

PIPER_MODEL="models/en_US-amy-medium.onnx"
PIPER_CONFIG="models/en_US-amy-medium.onnx.json"
PIPER_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium"

if [ ! -f "$PIPER_MODEL" ]; then
    echo "  Downloading voice model (~60MB)..."
    if command -v wget &> /dev/null; then
        wget -q --show-progress "$PIPER_BASE_URL/en_US-amy-medium.onnx" -O "$PIPER_MODEL"
        wget -q "$PIPER_BASE_URL/en_US-amy-medium.onnx.json" -O "$PIPER_CONFIG"
    elif command -v curl &> /dev/null; then
        curl -L --progress-bar "$PIPER_BASE_URL/en_US-amy-medium.onnx" -o "$PIPER_MODEL"
        curl -sL "$PIPER_BASE_URL/en_US-amy-medium.onnx.json" -o "$PIPER_CONFIG"
    else
        echo "  ⚠ Neither wget nor curl found. Download manually:"
        echo "    $PIPER_BASE_URL/en_US-amy-medium.onnx → $PIPER_MODEL"
        echo "    $PIPER_BASE_URL/en_US-amy-medium.onnx.json → $PIPER_CONFIG"
    fi
    echo "  ✓ Piper model downloaded"
else
    echo "  ✓ Piper model already exists"
fi

# ── 4. Download Piper binary (optional, faster than Python) ──
echo ""
echo "[4/5] Downloading Piper binary (optional, for faster TTS)..."
PIPER_DIR="models/piper"

if [ ! -f "$PIPER_DIR/piper" ]; then
    ARCH=$(uname -m)
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')

    if [ "$OS" = "linux" ] && [ "$ARCH" = "x86_64" ]; then
        PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"
    elif [ "$OS" = "linux" ] && [[ "$ARCH" == aarch64* ]]; then
        PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
    elif [ "$OS" = "darwin" ] && [ "$ARCH" = "x86_64" ]; then
        PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_x64.tar.gz"
    elif [ "$OS" = "darwin" ] && [ "$ARCH" = "arm64" ]; then
        PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_aarch64.tar.gz"
    else
        echo "  ⚠ No Piper binary for $OS/$ARCH. Using Python package."
        PIPER_URL=""
    fi

    if [ -n "$PIPER_URL" ]; then
        echo "  Downloading for $OS/$ARCH..."
        mkdir -p "$PIPER_DIR"
        if command -v wget &> /dev/null; then
            wget -q --show-progress "$PIPER_URL" -O /tmp/piper.tar.gz
        else
            curl -L --progress-bar "$PIPER_URL" -o /tmp/piper.tar.gz
        fi
        tar xzf /tmp/piper.tar.gz -C models/
        rm /tmp/piper.tar.gz
        chmod +x "$PIPER_DIR/piper" 2>/dev/null || true
        echo "  ✓ Piper binary installed"
    fi
else
    echo "  ✓ Piper binary already exists"
fi

# ── 5. Environment file ────────────────────────────────
echo ""
echo "[5/5] Checking environment configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ Created .env from .env.example"
    echo ""
    echo "  ⚠ IMPORTANT: Edit .env and add your GEMINI_API_KEY"
    echo "    Get one at: https://aistudio.google.com/app/apikey"
else
    echo "  ✓ .env already exists"
fi

# ── Done ───────────────────────────────────────────────
echo ""
echo "============================================="
echo "  Setup Complete!"
echo "============================================="
echo ""
echo "  Next steps:"
echo "    1. Edit .env with your GEMINI_API_KEY"
echo "    2. Activate venv:  source venv/bin/activate"
echo "    3. Test modules:   python -m tests.test_modules llm"
echo "    4. Run server:     python main.py"
echo ""
echo "  The server will listen on ws://0.0.0.0:8765/ws"
echo "  Update your ESP32 config.h with this PC's IP address."
echo ""
