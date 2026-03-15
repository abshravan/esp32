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
echo "[1/3] Creating Python virtual environment..."
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
echo "[2/3] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✓ Dependencies installed"

# ── 3. Environment file ────────────────────────────────
echo ""
echo "[3/3] Checking environment configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ Created .env from .env.example"
else
    echo "  ✓ .env already exists"
fi

# ── Done ───────────────────────────────────────────────
echo ""
echo "============================================="
echo "  Setup Complete!"
echo "============================================="
echo ""
echo "  Prerequisites:"
echo "    • Install Ollama:  https://ollama.com"
echo "    • Pull a model:    ollama pull llama3.2"
echo ""
echo "  Next steps:"
echo "    1. Activate venv:  source venv/bin/activate"
echo "    2. Test modules:   python -m tests.test_modules llm"
echo "    3. Run server:     python main.py"
echo ""
echo "  The server will listen on ws://0.0.0.0:8765/ws"
echo "  Update your ESP32 config.h with this PC's IP address."
echo ""
