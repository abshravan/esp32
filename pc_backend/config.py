"""
Central configuration for the voice assistant backend.
Loads from environment variables or .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Server ───────────────────────────────────────────
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", "8765"))

# ─── Audio Format (must match ESP32) ──────────────────
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2        # 16-bit = 2 bytes
CHANNELS = 1

# ─── Speech to Text (Faster-Whisper) ─────────────────
STT_MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "base.en")
# Options: tiny.en, base.en, small.en, medium.en, large-v3
# "base.en" is good balance of speed and accuracy
STT_DEVICE = os.getenv("STT_DEVICE", "cpu")
# "cpu" or "cuda" (if you have NVIDIA GPU + CTranslate2 CUDA)
STT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")
# "int8" for CPU, "float16" for CUDA

# ─── LLM (Ollama — local) ────────────────────────────
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """
You are a helpful, friendly voice assistant running on an ESP32 device.
Keep your responses concise and conversational — ideally 1-3 sentences.
The user is speaking to you, so respond naturally as in a spoken conversation.
Do not use markdown, bullet points, or formatting — just plain spoken text.
If you don't know something, say so briefly.
""".strip())

# ─── Conversation Memory ─────────────────────────────
# Number of previous turns to keep in context
MAX_CONVERSATION_TURNS = int(os.getenv("MAX_CONVERSATION_TURNS", "10"))

# ─── Audio Streaming ─────────────────────────────────
# Chunk size for streaming TTS audio back to ESP32
# 1024 bytes = 512 samples = 32ms at 16kHz
AUDIO_STREAM_CHUNK = 1024

