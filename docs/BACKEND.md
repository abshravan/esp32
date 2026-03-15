# PC Backend Documentation

Full reference for the Python backend located in `pc_backend/`.

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [Project Structure](#project-structure)
- [Modules](#modules)
  - [STT — Speech to Text (`modules/stt.py`)](#stt--speech-to-text-modulessttpy)
  - [LLM — Language Model (`modules/llm.py`)](#llm--language-model-modulesllmpy)
  - [TTS — Text to Speech (`modules/tts.py`)](#tts--text-to-speech-modulesttspy)
  - [LED Control (`modules/led.py`)](#led-control-modulesledpy)
  - [Weather (`modules/weather.py`)](#weather-modulesweatherpy)
- [WebSocket Protocol](#websocket-protocol)
- [REST Endpoints](#rest-endpoints)
- [Environment Variables Reference](#environment-variables-reference)
- [Troubleshooting](#troubleshooting)

---

## Overview

The backend is a FastAPI WebSocket server that orchestrates the full voice pipeline:

```
ESP32 sends PCM audio
        │
        ▼
  [STT] Faster-Whisper transcribes
        │
        ▼
  [LLM] Ollama generates a reply
        │  (LED command extracted here)
        ▼
  [TTS] pyttsx3 synthesizes speech
        │
        ▼
  PCM audio streamed back to ESP32
```

The pipeline runs as an `asyncio` Task, so the WebSocket receive loop is never blocked — cancel and start messages are handled in real time even while the pipeline is processing.

---

## Requirements

- **Python 3.10+** (uses `match`, `|` union types)
- **Ollama** running locally with a model pulled (e.g. `llama3.2`)
- Linux, macOS, or Windows (pyttsx3 uses the OS built-in TTS engine)

### System packages (Linux)

```bash
# espeak is required by pyttsx3
sudo apt install espeak espeak-data libespeak-dev ffmpeg
```

### GPU acceleration (optional)

Faster-Whisper can use an NVIDIA GPU via CTranslate2:

```bash
pip install faster-whisper[cuda]
# then set in .env:
# STT_DEVICE=cuda
# STT_COMPUTE_TYPE=float16
```

---

## Installation

```bash
cd pc_backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate       # Linux/macOS
# venv\Scripts\activate        # Windows

# Install dependencies
pip install -r requirements.txt

# Copy the example config
cp .env.example .env
```

Edit `.env` with your settings (see [Environment Variables Reference](#environment-variables-reference)).

---

## Configuration

All settings are in `config.py`, which reads from environment variables or a `.env` file in the `pc_backend/` directory.

### Minimal `.env` for local use

```env
WS_HOST=0.0.0.0
WS_PORT=8765

STT_MODEL_SIZE=base.en
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

WEATHER_CITY=London
```

### STT model size trade-offs

| Model | Size | Speed (CPU) | Accuracy |
|-------|------|-------------|----------|
| `tiny.en` | ~75 MB | Fastest | Basic |
| `base.en` | ~145 MB | Fast | Good (default) |
| `small.en` | ~465 MB | Moderate | Better |
| `medium.en` | ~1.5 GB | Slow | High |
| `large-v3` | ~3 GB | Very slow | Best |

The model is downloaded automatically from HuggingFace on first use.

---

## Running the Server

```bash
# Activate venv first
source venv/bin/activate

python main.py
```

On startup the server:
1. Prints connection info and model settings
2. Pre-loads STT, LLM, and TTS so the first request is fast
3. Starts uvicorn on `WS_HOST:WS_PORT`

```
============================================================
  ESP32 Voice Assistant — PC Backend
============================================================
  WebSocket:  ws://0.0.0.0:8765/ws
  STT Model:  base.en (cpu)
  LLM:        llama3.2 via http://localhost:11434
  TTS:        pyttsx3 (OS built-in)
  Audio:      16000Hz, 16-bit, mono
============================================================

[Startup] Pre-loading models...
[Startup] ✓ STT ready
[Startup] ✓ LLM ready
[Startup] ✓ TTS ready

[Server] Starting... Press Ctrl+C to stop.
```

---

## Project Structure

```
pc_backend/
├── main.py             # FastAPI app, WebSocket endpoint, VoiceSession
├── config.py           # All settings (reads from .env)
├── requirements.txt    # Python dependencies
├── setup.sh            # Optional setup helper script
├── .env.example        # Template for .env
├── modules/
│   ├── __init__.py
│   ├── stt.py          # Speech-to-Text (Faster-Whisper)
│   ├── llm.py          # LLM chat (Ollama)
│   ├── tts.py          # Text-to-Speech (pyttsx3)
│   ├── led.py          # LED command parsing
│   └── weather.py      # Weather context (wttr.in)
└── tests/
    ├── __init__.py
    ├── test_ws_client.py
    └── test_modules.py
```

---

## Modules

### STT — Speech to Text (`modules/stt.py`)

Uses **Faster-Whisper** (CTranslate2-optimized Whisper) for offline transcription.

#### Class: `SpeechToText`

| Method | Description |
|--------|-------------|
| `add_audio_chunk(chunk: bytes)` | Buffer a raw PCM chunk (16 kHz, 16-bit, mono). |
| `get_buffer_duration() → float` | Current buffer length in seconds. |
| `clear_buffer()` | Discard buffered audio. |
| `transcribe() → str` | Transcribe buffered audio, clear buffer, return text. |

**Transcription process:**
1. Concatenate all buffered chunks into one numpy float32 array
2. Run Faster-Whisper with VAD (Voice Activity Detection) filter to strip silence
3. If VAD removes everything (quiet-but-valid speech), retry without VAD as a fallback
4. Audio shorter than 0.3 seconds is skipped automatically

**Audio cap:** Chunks are rejected once the buffer exceeds 60 seconds to prevent unbounded memory growth. The ESP32 firmware also auto-stops after `MAX_LISTEN_SECONDS` (default 60 s).

#### Singleton

```python
from modules.stt import get_stt
stt = get_stt()   # Returns the shared instance (created on first call)
```

---

### LLM — Language Model (`modules/llm.py`)

Uses **Ollama** running locally. Any model available in Ollama can be used.

#### Class: `LLMChat`

| Method | Description |
|--------|-------------|
| `chat(user_text: str) → str` | Send a message, get a response. Maintains history. |
| `clear_history()` | Reset conversation memory. |
| `get_history_summary() → str` | Returns `"N turns in memory"`. |

**Context injected into every system prompt:**
- Current date and time
- Live weather from wttr.in (if `WEATHER_CITY` is set)
- LED control instructions (the LLM is told to append `[LED:colorname]`)

**Conversation memory:** Up to `MAX_CONVERSATION_TURNS` (default 10) turn pairs are kept. Older turns are dropped from the front of the list (sliding window).

**Token cap:** `MAX_RESPONSE_TOKENS` (default 80) is passed as `num_predict` to Ollama. This keeps responses short and TTS under ~5 seconds.

**Retry:** Up to 3 attempts with 1-second sleep between retries on network errors.

#### Singleton

```python
from modules.llm import get_llm
llm = get_llm()
response = llm.chat("What time is it?")
```

---

### TTS — Text to Speech (`modules/tts.py`)

Uses **pyttsx3** with the OS built-in speech engine:
- **Linux:** espeak / espeak-ng
- **macOS:** NSSpeechSynthesizer
- **Windows:** SAPI5

No model downloads required. Audio is resampled to 16 kHz mono to match the ESP32.

#### Class: `TextToSpeech`

| Method | Description |
|--------|-------------|
| `synthesize(text: str) → bytes` | Convert text to raw PCM (16 kHz, 16-bit, mono). |
| `synthesize_chunks(text, chunk_size) → generator` | Yield PCM in `chunk_size` byte chunks. |

**Implementation notes:**
- A **fresh pyttsx3 engine is created per call**. Reusing an engine across calls causes `runAndWait()` to deadlock on the second call on Linux (espeak leaves its event loop in a dirty state).
- Output is written to a temp WAV file via `save_to_file()`, then read back and resampled.
- Stereo output (some engines on Windows/macOS) is mixed to mono before resampling.
- Resampling uses linear interpolation — sufficient quality for voice at 16 kHz.

**Speech rate:** Set to 160 words/minute (default pyttsx3 rate is ~200, which is fast for voice assistant use).

#### Singleton

```python
from modules.tts import get_tts
tts = get_tts()
pcm = tts.synthesize("Hello, how can I help?")
```

---

### LED Control (`modules/led.py`)

Parses `[LED:colorname]` tags from LLM responses.

#### Function: `parse_led_command`

```python
from modules.led import parse_led_command

clean_text, rgb = parse_led_command("Turning it blue. [LED:blue]")
# clean_text = "Turning it blue."
# rgb = (0, 0, 255)

clean_text, rgb = parse_led_command("Hello there.")
# clean_text = "Hello there."
# rgb = None
```

If a tag is found:
- The tag is stripped from the text (so TTS does not speak it)
- The RGB tuple is returned
- The backend sends `{"type":"led","text":"r,g,b"}` to the ESP32 immediately

Supported color names: `red`, `green`, `blue`, `white`, `yellow`, `orange`, `purple`, `pink`, `cyan`, `warm white`, `off`.

Unknown color names cause the tag to be stripped but no LED command is sent.

---

### Weather (`modules/weather.py`)

Fetches live weather from [wttr.in](https://wttr.in) — no API key required.

#### Class: `WeatherClient`

| Method | Description |
|--------|-------------|
| `get_summary() → str \| None` | Returns a short weather string for the LLM prompt, or `None` on failure. |

**Example output injected into the system prompt:**
```
Current weather in London: Partly cloudy, 14°C (57°F), humidity 72%, wind 18 km/h.
```

**Caching:** Weather is cached for 10 minutes (`CACHE_TTL_SECONDS = 600`). If the network is unreachable, the last cached value is returned. If there is no cache yet, `None` is returned and the LLM answers without weather context.

**Configuration:** Set `WEATHER_CITY` in `.env`. Leave it empty to disable weather context.

#### Singleton

```python
from modules.weather import get_weather
summary = get_weather().get_summary()
```

---

## WebSocket Protocol

The server listens at `ws://<WS_HOST>:<WS_PORT>/ws`.

### Messages received from ESP32

| Format | Content | Action |
|--------|---------|--------|
| Text JSON | `{"type":"start_listening"}` | Start a new session, clear audio buffer |
| Text JSON | `{"type":"stop_listening"}` | Stop buffering, launch pipeline task |
| Text JSON | `{"type":"cancel"}` | Set `is_cancelled = True`, pipeline aborts at next checkpoint |
| Binary | Raw PCM bytes | Appended to audio buffer (while listening) |

### Messages sent to ESP32

| Format | Content | When |
|--------|---------|------|
| Text JSON | `{"type":"thinking"}` | Pipeline started, STT running |
| Text JSON | `{"type":"transcript","text":"..."}` | After STT completes |
| Text JSON | `{"type":"response","text":"..."}` | LLM response text (before TTS) |
| Text JSON | `{"type":"speaking"}` | About to stream TTS audio |
| Text JSON | `{"type":"led","text":"r,g,b"}` | LED color change |
| Text JSON | `{"type":"audio_end"}` | All TTS audio frames sent |
| Text JSON | `{"type":"error","text":"..."}` | Pipeline error |
| Binary | Raw PCM bytes | TTS audio in `AUDIO_STREAM_CHUNK`-byte frames |

### Session lifecycle

```
ESP32                          Backend
  │── start_listening ────────▶│  new_session(), clear buffer
  │── [PCM frames] ───────────▶│  stt.add_audio_chunk()
  │── stop_listening ──────────▶│  create pipeline Task
  │◀─── thinking ──────────────│  STT started
  │◀─── transcript ────────────│  STT result
  │◀─── response ──────────────│  LLM response text
  │◀─── speaking ──────────────│  TTS about to stream
  │◀─── [PCM frames] ──────────│  TTS audio
  │◀─── audio_end ─────────────│  Done
```

If the ESP32 sends `cancel` at any point, the pipeline's `stale()` check returns `True` at the next checkpoint and the task exits without sending further messages.

### Concurrency

The WebSocket receive loop and the pipeline run as concurrent `asyncio` coroutines. A `_ws_lock` (`asyncio.Lock`) serializes all outgoing writes (text and binary) to prevent race conditions between the pipeline's `send_bytes()` calls and the uvicorn/wsproto layer's automatic PONG responses.

---

## REST Endpoints

### `GET /health`

Returns the current server configuration. Useful for checking the server is up and which models are loaded.

```bash
curl http://localhost:8765/health
```

```json
{
  "status": "ok",
  "stt_model": "base.en",
  "llm_model": "llama3.2",
  "llm_url": "http://localhost:11434",
  "tts_engine": "pyttsx3"
}
```

---

## Environment Variables Reference

All variables are optional — defaults are shown.

| Variable | Default | Description |
|----------|---------|-------------|
| `WS_HOST` | `0.0.0.0` | Host to bind (use `0.0.0.0` for LAN access) |
| `WS_PORT` | `8765` | WebSocket server port |
| `STT_MODEL_SIZE` | `base.en` | Faster-Whisper model (`tiny.en` → `large-v3`) |
| `STT_DEVICE` | `cpu` | `cpu` or `cuda` |
| `STT_COMPUTE_TYPE` | `int8` | `int8` (CPU) or `float16` (CUDA) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `llama3.2` | Model name (must be pulled in Ollama) |
| `SYSTEM_PROMPT` | *(built-in voice assistant prompt)* | Override the LLM system prompt |
| `MAX_RESPONSE_TOKENS` | `80` | Hard cap on LLM output tokens |
| `MAX_CONVERSATION_TURNS` | `10` | Turns of history kept in context |
| `WEATHER_CITY` | `London` | City for weather context. Set empty to disable. |

---

## Troubleshooting

### `ollama: command not found` / LLM not reachable

Install Ollama from [ollama.com](https://ollama.com) and pull a model:

```bash
ollama pull llama3.2
ollama serve   # if not already running as a service
```

Check connectivity:

```bash
curl http://localhost:11434/api/tags
```

### STT model download fails

Faster-Whisper downloads models from HuggingFace on first use. If behind a proxy or firewall, pre-download manually:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('base.en')"
```

### `pyttsx3` TTS silent / no audio returned

On Linux, ensure `espeak` is installed:

```bash
sudo apt install espeak
python -c "import pyttsx3; e = pyttsx3.init(); e.say('test'); e.runAndWait()"
```

If `runAndWait()` hangs, kill any orphan `espeak` processes:

```bash
pkill -f espeak
```

### TTS audio sounds garbled on ESP32

The backend resamples TTS audio from the OS native rate (e.g., 22050 Hz) to 16000 Hz. Both sides must agree on sample rate — `SAMPLE_RATE` in `config.py` must match `SAMPLE_RATE` in the ESP32 `config.h`.

### WebSocket connection refused

- Confirm the server is running (`python main.py`)
- Check `WS_HOST` in the ESP32 firmware matches the PC's LAN IP
- Ensure port 8765 is not blocked by the firewall:
  ```bash
  # Linux
  sudo ufw allow 8765/tcp
  ```

### Pipeline hangs / never sends `audio_end`

This usually means the LLM timed out (30-second limit) or TTS returned empty bytes. Check the server terminal for `[Pipeline]` log lines to identify which step stalled.

### High latency

| Bottleneck | Fix |
|------------|-----|
| STT slow | Upgrade to GPU (`STT_DEVICE=cuda`) or downsize model (`tiny.en`) |
| LLM slow | Use a smaller model (`llama3.2:1b`) or upgrade hardware |
| TTS slow | pyttsx3 on Linux via espeak is slow — this is expected (~400 ms for 1–2 sentences) |
| Network | Ensure ESP32 and PC are on the same 5 GHz WiFi network |
