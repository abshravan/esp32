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
You are a concise voice assistant on an ESP32 device.
STRICT RULES — follow every rule on every response:
- Answer in 1-2 short sentences MAXIMUM. Never more.
- No lists, no markdown, no bullet points, no headers.
- No lengthy explanations or background. Get to the point immediately.
- If asked about a broad topic, give ONE key fact and offer to elaborate.
- Plain spoken English only, as if talking to someone face-to-face.
""".strip())

# Hard cap on LLM output tokens — keeps TTS audio under ~5 seconds.
# 80 tokens ≈ 60 words ≈ 2 short sentences at typical speaking pace.
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "80"))

# ─── Conversation Memory ─────────────────────────────
# Number of previous turns to keep in context
MAX_CONVERSATION_TURNS = int(os.getenv("MAX_CONVERSATION_TURNS", "10"))

# ─── Weather (wttr.in — no API key required) ─────────
# Set your city; leave empty to disable weather context.
WEATHER_CITY = os.getenv("WEATHER_CITY", "London")

# ─── Audio Streaming ─────────────────────────────────
# Chunk size for streaming TTS audio back to ESP32
# 1024 bytes = 512 samples = 32ms at 16kHz
AUDIO_STREAM_CHUNK = 1024

