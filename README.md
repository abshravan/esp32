# ESP32 Voice Assistant

A low-latency voice assistant using ESP32 hardware with a PC-based AI backend.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      ESP32 Device                        │
│                                                          │
│  ┌──────────┐   I2S   ┌──────────┐   WiFi/WS           │
│  │ INMP441  │───────▶│  ESP32   │◀──────────────┐      │
│  │   Mic    │         │          │               │      │
│  └──────────┘         │  State   │   WiFi/WS     │      │
│                       │  Machine │──────────────▶│      │
│  ┌──────────┐   I2S   │          │               │      │
│  │MAX98357A │◀───────│          │               │      │
│  │ Speaker  │         └────┬─────┘               │      │
│  └──────────┘              │                     │      │
│                       ┌────┴─────┐               │      │
│                       │ SSD1306  │               │      │
│                       │  OLED    │               │      │
│                       └──────────┘               │      │
└──────────────────────────────────────────────────┼──────┘
                                                   │
                          WebSocket (binary frames) │
                                                   │
┌──────────────────────────────────────────────────┼──────┐
│                     PC Backend                    │      │
│                                                   ▼      │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │  WebSocket  │───▶│ Audio Stream │───▶│  Faster    │  │
│  │   Server    │    │   Handler    │    │  Whisper   │  │
│  │ (FastAPI)   │    └──────────────┘    │   STT      │  │
│  │             │                         └─────┬──────┘  │
│  │             │    ┌──────────────┐          │         │
│  │             │◀───│   Piper TTS  │◀─────┐   │         │
│  │             │    │  (streaming) │      │   ▼         │
│  └─────────────┘    └──────────────┘    ┌─┴────────┐   │
│                                          │  Gemini  │   │
│                                          │  2.1     │   │
│                                          │  Flash   │   │
│                                          └──────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Hardware Wiring

### INMP441 I2S Microphone → ESP32

| INMP441 Pin | ESP32 Pin | Notes              |
|-------------|----------|--------------------|
| VDD         | 3.3V     | Power              |
| GND         | GND      | Ground             |
| SD          | GPIO 32  | Serial Data        |
| WS          | GPIO 25  | Word Select (LRCK) |
| SCK         | GPIO 33  | Serial Clock       |
| L/R         | GND      | Left channel       |

### MAX98357A I2S Amplifier → ESP32

| MAX98357A Pin | ESP32 Pin | Notes              |
|---------------|----------|--------------------|
| VIN           | 5V       | Power (or 3.3V)   |
| GND           | GND      | Ground             |
| DIN           | GPIO 26  | Serial Data        |
| BCLK          | GPIO 27  | Bit Clock          |
| LRC           | GPIO 14  | Left/Right Clock   |
| GAIN          | NC       | Default 9dB gain   |
| SD            | NC       | Leave floating=ON  |

### SSD1306 OLED Display → ESP32

| SSD1306 Pin | ESP32 Pin | Notes        |
|-------------|----------|--------------|
| VCC         | 3.3V     | Power        |
| GND         | GND      | Ground       |
| SDA         | GPIO 21  | I2C Data     |
| SCL         | GPIO 22  | I2C Clock    |

### Boot Button (Push-to-Talk)

| Button Pin | ESP32 Pin | Notes              |
|------------|----------|--------------------|
| Pin 1      | GPIO 0   | Built-in BOOT btn  |
| Pin 2      | GND      | (already wired)    |

## Protocol

### WebSocket Messages

**ESP32 → PC:**
- Binary frames: Raw PCM audio (16kHz, 16-bit, mono)
- Text: `{"type":"start_listening"}` — begin of utterance
- Text: `{"type":"stop_listening"}` — end of utterance
- Text: `{"type":"cancel"}` — interrupt playback

**PC → ESP32:**
- Binary frames: PCM audio response (16kHz, 16-bit, mono)
- Text: `{"type":"status","state":"thinking"}` — status update
- Text: `{"type":"status","state":"speaking"}` — about to send audio
- Text: `{"type":"audio_end"}` — response audio complete
- Text: `{"type":"transcript","text":"..."}` — what user said
- Text: `{"type":"response","text":"..."}` — LLM response text

## Quick Start

### 1. PC Backend Setup

```bash
cd pc_backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

pip install -r requirements.txt

# Download Piper TTS voice model
mkdir -p models
cd models
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
tar xzf piper_linux_x86_64.tar.gz
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json
cd ..

# Set API key
export GEMINI_API_KEY="your-key-here"

# Run server
python main.py
```

### 2. ESP32 Firmware

1. Open `esp32_firmware/` in PlatformIO or Arduino IDE
2. Edit `include/config.h` with your WiFi and server details
3. Flash to ESP32
4. Press BOOT button to talk

## Latency Budget

| Stage                | Target   |
|----------------------|----------|
| Audio capture        | ~200ms   |
| WiFi transfer        | ~50ms    |
| Speech-to-text       | ~300ms   |
| LLM response         | ~800ms   |
| Text-to-speech       | ~400ms   |
| WiFi transfer back   | ~50ms    |
| Audio playback start | ~100ms   |
| **Total**            | **~2s**  |
