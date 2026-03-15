# ESP32 Voice Assistant

A low-latency, fully offline-capable voice assistant built on an ESP32 microcontroller with a Python PC backend. Speak into the microphone, get an AI response spoken back through the speaker — end-to-end in roughly 2 seconds.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      ESP32 Device                        │
│                                                          │
│  ┌──────────┐   I2S   ┌──────────┐   WiFi/WS            │
│  │ INMP441  │───────▶│  ESP32   │◀──────────────┐       │
│  │   Mic    │         │          │               │       │
│  └──────────┘         │  State   │   WiFi/WS     │       │
│                       │  Machine │──────────────▶│       │
│  ┌──────────┐   I2S   │          │               │       │
│  │MAX98357A │◀───────│          │               │       │
│  │ Speaker  │         └────┬─────┘               │       │
│  └──────────┘              │                     │       │
│                       ┌────┴─────┐               │       │
│  ┌──────────┐   I2C   │ SSD1306  │               │       │
│  │WS2812B   │         │  OLED    │               │       │
│  │   LED    │         └──────────┘               │       │
│  └──────────┘                                    │       │
└──────────────────────────────────────────────────┼───────┘
                                                   │
                          WebSocket (binary frames) │
                                                   │
┌──────────────────────────────────────────────────┼───────┐
│                     PC Backend                    │       │
│                                                   ▼       │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐   │
│  │  WebSocket  │───▶│ Audio Buffer │───▶│  Faster-   │   │
│  │   Server    │    │   Handler    │    │  Whisper   │   │
│  │ (FastAPI)   │    └──────────────┘    │   (STT)    │   │
│  │             │                         └─────┬──────┘   │
│  │             │    ┌──────────────┐           │          │
│  │             │◀───│  pyttsx3 TTS │◀─────┐    │          │
│  │             │    │  (streaming) │      │    ▼          │
│  └─────────────┘    └──────────────┘    ┌─┴────────┐     │
│                                          │  Ollama  │     │
│                                          │  LLM     │     │
│                                          └──────────┘     │
└──────────────────────────────────────────────────────────┘
```

**Pipeline:** Push button → mic streams PCM over WiFi → Faster-Whisper transcribes → Ollama LLM replies → pyttsx3 speaks → PCM streams back → speaker plays.

## Hardware

| Component | Purpose |
|-----------|---------|
| ESP32 dev board | Main MCU |
| INMP441 | I2S MEMS microphone |
| MAX98357A | I2S mono amplifier |
| SSD1306 | 128×64 OLED status display |
| WS2812B | RGB LED (voice-controlled color) |
| Speaker (4–8 Ω) | Audio output |

## Wiring

### INMP441 Microphone

| INMP441 | ESP32 | Notes |
|---------|-------|-------|
| VDD | 3.3V | Power |
| GND | GND | Ground |
| SD | GPIO 32 | Serial Data |
| WS | GPIO 25 | Word Select (LRCK) |
| SCK | GPIO 33 | Serial Clock |
| L/R | GND | Left channel select |

### MAX98357A Amplifier

| MAX98357A | ESP32 | Notes |
|-----------|-------|-------|
| VIN | 5V | Power |
| GND | GND | Ground |
| DIN | GPIO 26 | Serial Data |
| BCLK | GPIO 27 | Bit Clock |
| LRC | GPIO 14 | Left/Right Clock |
| GAIN | NC | Default 9 dB gain |
| SD | NC | Float = always on |

### SSD1306 OLED

| SSD1306 | ESP32 | Notes |
|---------|-------|-------|
| VCC | 3.3V | Power |
| GND | GND | Ground |
| SDA | GPIO 21 | I2C Data |
| SCL | GPIO 22 | I2C Clock |

### WS2812B LED

| WS2812B | ESP32 | Notes |
|---------|-------|-------|
| VCC | 5V | Power — do not use 3.3V |
| GND | GND | Shared ground |
| DIN | GPIO 4 | Data (300Ω series resistor recommended) |

### Push-to-Talk Button

| Button | ESP32 | Notes |
|--------|-------|-------|
| Pin 1 | GPIO 0 | Built-in BOOT button |
| Pin 2 | GND | Already wired on board |

## Quick Start

### 1. PC Backend

```bash
cd pc_backend
python -m venv venv
source venv/bin/activate       # Linux/macOS
# venv\Scripts\activate        # Windows

pip install -r requirements.txt

# Install Ollama and pull a model
# https://ollama.com
ollama pull llama3.2

# Configure (copy and edit the example env file)
cp .env.example .env
# Edit .env: set WS_HOST, OLLAMA_MODEL, WEATHER_CITY, etc.

python main.py
```

The server starts on `ws://0.0.0.0:8765/ws` by default.
Health check: `http://localhost:8765/health`

### 2. ESP32 Firmware

1. Open `esp32_firmware/` in **PlatformIO** (recommended) or Arduino IDE
2. Edit `include/config.h`:
   - Set `WIFI_SSID` and `WIFI_PASSWORD`
   - Set `WS_HOST` to your PC's local IP address
3. Flash: `pio run --target upload` (or use the IDE upload button)
4. Open Serial Monitor at **115200 baud**

### 3. Use It

| Action | How |
|--------|-----|
| Start recording | Tap BOOT button **or** type `s` in Serial Monitor |
| Stop & process | Tap BOOT button again **or** type `e` |
| Cancel / interrupt | Tap BOOT during playback **or** type `c` |
| Restart ESP32 | Type `r` |
| LED color control | Say "turn the light red" (or any supported color) |

## WebSocket Protocol

**ESP32 → PC (text):**

| Message | Meaning |
|---------|---------|
| `{"type":"start_listening"}` | Begin of utterance |
| `{"type":"stop_listening"}` | End of utterance, start processing |
| `{"type":"cancel"}` | Interrupt current pipeline |

**ESP32 → PC (binary):** Raw PCM audio — 16 kHz, 16-bit, mono

**PC → ESP32 (text):**

| Message | Meaning |
|---------|---------|
| `{"type":"thinking"}` | STT/LLM processing started |
| `{"type":"speaking"}` | TTS audio about to stream |
| `{"type":"audio_end"}` | All audio frames sent |
| `{"type":"transcript","text":"..."}` | What the user said |
| `{"type":"response","text":"..."}` | LLM reply text |
| `{"type":"led","text":"r,g,b"}` | Set WS2812B color |
| `{"type":"error","text":"..."}` | Pipeline error |

**PC → ESP32 (binary):** PCM audio response — 16 kHz, 16-bit, mono

## Latency Budget

| Stage | Target |
|-------|--------|
| Audio capture | ~200 ms |
| WiFi transfer | ~50 ms |
| Speech-to-text | ~300 ms |
| LLM response | ~800 ms |
| Text-to-speech | ~400 ms |
| WiFi transfer back | ~50 ms |
| Audio playback start | ~100 ms |
| **Total** | **~2 s** |

## Documentation

- [Arduino Firmware Documentation](docs/ARDUINO_FIRMWARE.md)
- [PC Backend Documentation](docs/BACKEND.md)
