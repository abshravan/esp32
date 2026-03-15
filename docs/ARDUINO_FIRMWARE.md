# Arduino / ESP32 Firmware Documentation

Full reference for the ESP32 firmware located in `esp32_firmware/`.

## Table of Contents

- [Overview](#overview)
- [Hardware Requirements](#hardware-requirements)
- [Pin Assignments](#pin-assignments)
- [Project Structure](#project-structure)
- [Dependencies](#dependencies)
- [Configuration (`config.h`)](#configuration-configh)
- [State Machine](#state-machine)
- [Modules](#modules)
  - [Audio (`audio.h`)](#audio-audioh)
  - [WebSocket Client (`ws_client.h`)](#websocket-client-ws_clienth)
  - [Display (`display.h`)](#display-displayh)
  - [Main Loop (`main.cpp`)](#main-loop-maincpp)
- [Flashing the Firmware](#flashing-the-firmware)
- [Serial Monitor Commands](#serial-monitor-commands)
- [LED Color Control](#led-color-control)
- [Troubleshooting](#troubleshooting)

---

## Overview

The firmware implements a push-to-talk voice assistant that:

1. Captures audio from an INMP441 I2S microphone
2. Streams raw PCM audio over WebSocket to a PC backend
3. Receives synthesized speech PCM back and plays it through a MAX98357A amplifier
4. Shows status on an SSD1306 OLED display
5. Controls a WS2812B RGB LED in response to voice commands

The entire flow is driven by a five-state machine. Audio is streamed in real time — no local buffering until recording ends.

---

## Hardware Requirements

| Part | Specification |
|------|--------------|
| ESP32 dev board | Standard 38-pin devkit (WROOM or WROVER) |
| INMP441 | I2S MEMS microphone module |
| MAX98357A | I2S Class-D mono amplifier |
| Speaker | 4 Ω or 8 Ω, any wattage |
| SSD1306 | 128×64 OLED, I2C, 3.3V |
| WS2812B | Single RGB LED (or short strip, adjust `LED_COUNT`) |
| Push button | Optional — BOOT button (GPIO 0) is used by default |

---

## Pin Assignments

All pins are defined in `include/config.h` and can be changed there.

### INMP441 I2S Microphone

| INMP441 Pin | GPIO | Config Macro |
|-------------|------|-------------|
| WS (LRCK) | 25 | `MIC_I2S_WS` |
| SCK (BCLK) | 33 | `MIC_I2S_SCK` |
| SD (DOUT) | 32 | `MIC_I2S_SD` |
| VDD | 3.3V | — |
| GND | GND | — |
| L/R | GND | Left channel (tie HIGH for right) |

> **Note:** If you get silence from the microphone, the L/R pin may be wired to a different level than the firmware expects. Change `I2S_CHANNEL_FMT_ONLY_LEFT` to `I2S_CHANNEL_FMT_ONLY_RIGHT` in `audio.h → beginMicrophone()`.

### MAX98357A I2S Amplifier

| MAX98357A Pin | GPIO | Config Macro |
|---------------|------|-------------|
| BCLK | 27 | `SPK_I2S_BCLK` |
| LRC | 14 | `SPK_I2S_LRC` |
| DIN | 26 | `SPK_I2S_DIN` |
| VIN | 5V | — |
| GND | GND | — |
| GAIN | NC | 9 dB (default) |
| SD | NC | Float = always enabled |

### SSD1306 OLED (I2C)

| SSD1306 Pin | GPIO | Config Macro |
|-------------|------|-------------|
| SDA | 21 | `OLED_SDA` |
| SCL | 22 | `OLED_SCL` |
| VCC | 3.3V | — |
| GND | GND | — |

Default I2C address: `0x3C` (`OLED_ADDR`). Some modules use `0x3D`.

### WS2812B RGB LED

| WS2812B Pin | GPIO | Config Macro |
|-------------|------|-------------|
| DIN | 4 | `LED_PIN` |
| VCC | **5V** | — |
| GND | GND | — |

> **Important:** The WS2812B requires 5V power. The data line at 3.3V usually works in practice because the threshold is ~0.7×VCC (3.5V) and many chips accept 3.3V as valid HIGH — but add a 74AHCT125 level shifter for guaranteed reliability. Always include a 300Ω series resistor on the data line.

### Push-to-Talk Button

| Pin | GPIO | Config Macro |
|-----|------|-------------|
| Button | 0 | `BTN_PIN` |

GPIO 0 is the built-in BOOT button on most ESP32 dev boards. No external button is required.

---

## Project Structure

```
esp32_firmware/
├── platformio.ini          # PlatformIO build configuration
├── include/
│   ├── config.h            # All pin and tuning constants
│   ├── audio.h             # I2S mic + speaker driver, ring buffer
│   ├── ws_client.h         # WebSocket client wrapper
│   └── display.h           # SSD1306 OLED driver
└── src/
    └── main.cpp            # State machine, setup(), loop()
```

---

## Dependencies

Managed automatically by PlatformIO via `platformio.ini`:

| Library | Version | Purpose |
|---------|---------|---------|
| `links2004/WebSockets` | ^2.4.1 | WebSocket client over WiFi |
| `adafruit/Adafruit SSD1306` | ^2.5.7 | OLED display driver |
| `adafruit/Adafruit GFX Library` | ^1.11.5 | Graphics primitives for OLED |
| `bblanchon/ArduinoJson` | ^6.21.3 | JSON serialization/deserialization |
| `fastled/FastLED` | ^3.6.0 | WS2812B LED control |

Built-in ESP32 IDF components used:
- `driver/i2s.h` — I2S audio DMA
- `WiFi.h` — WiFi station mode

---

## Configuration (`config.h`)

Edit `include/config.h` before flashing. Every tunable value lives here.

### WiFi

```cpp
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"
```

### WebSocket Server

```cpp
#define WS_HOST   "192.168.1.100"   // PC's local IP address
#define WS_PORT   8765
#define WS_PATH   "/ws"
```

Find your PC's IP with `ip a` (Linux/macOS) or `ipconfig` (Windows).

### Audio

| Macro | Default | Description |
|-------|---------|-------------|
| `SAMPLE_RATE` | 16000 | Sample rate in Hz (must match backend) |
| `BITS_PER_SAMPLE` | 16 | Bit depth |
| `AUDIO_CHUNK_SAMPLES` | 512 | DMA buffer size (512 samples = 32 ms) |
| `PLAYBACK_BUF_SIZE` | ~64 KB | Ring buffer (~2 seconds of audio) |

### Behavior

| Macro | Default | Description |
|-------|---------|-------------|
| `MAX_LISTEN_SECONDS` | 60 | Auto-stop recording after this many seconds |
| `POST_SPEAK_SILENCE_MS` | 500 | Mic mute duration after playback ends (echo suppression) |
| `BTN_DEBOUNCE_MS` | 100 | Button debounce window in ms |
| `MIN_LISTEN_MS` | 500 | Ignore a stop-tap within this window of starting |

### Microphone Gain

Defined in `audio.h`:

```cpp
int micGain = 400;  // 4× amplification
```

The INMP441 outputs a low-amplitude signal in 16-bit I2S mode. The default 4× gain works well in a quiet room. Increase if the transcription misses speech; decrease if audio clips (peak amplitude > 32767 in serial logs).

---

## State Machine

```
         ┌──────────┐
    ┌───▶│  IDLE    │◀────────────────────────────┐
    │    └────┬─────┘                              │
    │    tap/s│                                    │
    │    ┌────▼──────┐                             │
    │    │ LISTENING │                             │
    │    └────┬──────┘                             │
    │    tap/e│                                    │
    │    ┌────▼──────┐   error / timeout           │
    │    │ THINKING  │────────────────────────────▶│
    │    └────┬──────┘                             │
    │ speaking│                                    │
    │    ┌────▼──────┐   audio_end + buffer empty  │
    │    │ SPEAKING  │────────────────────────────▶│
    │    └───────────┘                             │
    │         │ cancel (c)                         │
    └─────────┘──────────────────────────────────▶│
                                                   │
         ┌──────────────┐                          │
         │  CONNECTING  │──────(WS connected)──────┘
         └──────────────┘
```

| State | Display | What happens |
|-------|---------|-------------|
| `STATE_CONNECTING` | "Connecting..." | WebSocket reconnect loop |
| `STATE_IDLE` | "Ready" animation | Waiting for input |
| `STATE_LISTENING` | "Listening..." | Mic active, PCM streaming to server |
| `STATE_THINKING` | Dot animation | Waiting for backend pipeline |
| `STATE_SPEAKING` | "Speaking..." | Streaming PCM from ring buffer to speaker |

Transitions are triggered by:
- WebSocket messages from the server (`thinking`, `speaking`, `audio_end`, `error`)
- Button taps or serial commands from the user
- Timeouts (30 s thinking timeout, `MAX_LISTEN_SECONDS` auto-stop)

---

## Modules

### Audio (`audio.h`)

Contains two classes:

#### `RingBuffer`

A simple thread-safe ring buffer allocated from heap. Used as the playback buffer between incoming WebSocket audio frames and the I2S DMA.

| Method | Description |
|--------|-------------|
| `init(size)` | Allocate buffer. Returns `false` on OOM. |
| `write(data, len)` | Write up to `len` bytes. Returns bytes written (drops on overflow). |
| `read(data, len)` | Read up to `len` bytes. Returns bytes read. |
| `available()` | Bytes currently in buffer. |
| `freeSpace()` | Bytes until full. |
| `clear()` | Reset pointers (discard contents). |

#### `Audio`

Wraps the ESP-IDF I2S driver for both mic (I2S port 0) and speaker (I2S port 1).

| Method | Description |
|--------|-------------|
| `beginMicrophone()` | Install I2S driver, configure INMP441 pins. |
| `beginSpeaker()` | Install I2S driver, configure MAX98357A pins, allocate ring buffer. |
| `readMicrophone(buf, len)` | Read one DMA chunk from mic, apply software gain. |
| `feedSpeaker()` | Drain ring buffer into I2S DMA (call every loop iteration during `STATE_SPEAKING`). |
| `stopSpeaker()` | Zero the DMA buffer and clear ring buffer immediately (for cancel). |
| `muteMicrophone()` | Stop I2S RX (prevents echo feedback during playback). |
| `unmuteMicrophone()` | Restart I2S RX and flush stale DMA data. |
| `setMicGain(percent)` | Set software gain (100 = 1×, 400 = 4×). |

---

### WebSocket Client (`ws_client.h`)

Wraps `WebSocketsClient` (links2004 library) with a callback-based API.

```cpp
wsClient.onConnection(callback);   // void(bool connected)
wsClient.onText(callback);         // void(const char* type, const char* data)
wsClient.onBinary(callback);       // void(const uint8_t* data, size_t len)

wsClient.begin();                  // Connect to WS_HOST:WS_PORT/WS_PATH
wsClient.loop();                   // Must be called every loop() iteration
wsClient.sendAudio(data, len);     // Send binary PCM frame
wsClient.sendControl("type");      // Send {"type":"..."} JSON text frame
wsClient.isConnected();            // Returns bool
```

**Heartbeat:** Sends a PING every 15 seconds with a 3-second timeout (2 retries before reconnect). This keeps the connection alive through NAT/router idle timeouts.

**Reconnect:** Automatically retries every 3 seconds on disconnect.

Text messages are parsed with ArduinoJson. The `type` field is forwarded to `onText`; the `text` field (if present) is forwarded as the `data` argument.

---

### Display (`display.h`)

Wraps `Adafruit_SSD1306` to show state-specific messages on the 128×64 OLED.

| Method | Description |
|--------|-------------|
| `begin()` | Initialize I2C and OLED. Returns `false` on failure. |
| `showState(state)` | Render the appropriate screen for the given `AssistantState`. |
| `showMessage(line1, line2)` | Display two lines of text. |
| `showTranscript(text)` | Display the transcribed user speech. |

State screens:

| State | Display content |
|-------|----------------|
| CONNECTING | "Connecting..." with WiFi icon |
| IDLE | "Say something!" with pulse animation |
| LISTENING | "Listening..." with animated mic |
| THINKING | "Thinking..." with dot animation |
| SPEAKING | "Speaking..." with speaker icon |

---

### Main Loop (`main.cpp`)

`setup()` runs once:
1. Initialize LEDs (off), button pin, display
2. Connect to WiFi (halts on failure)
3. Initialize microphone and speaker (halts on failure)
4. Register WebSocket callbacks and connect

`loop()` runs continuously:
1. `wsClient.loop()` — service WebSocket receive/send
2. `handleButton()` — debounced tap detection
3. `handleSerial()` — Serial Monitor commands
4. State-specific work (capture audio / feed speaker / update display)
5. `yield()` — prevent watchdog timer reset

**Echo suppression:** When entering `STATE_SPEAKING`, the mic is muted via `audio.muteMicrophone()`. After playback ends, the mic stays muted for `POST_SPEAK_SILENCE_MS` (default 500 ms) to let room echo decay before the next recording starts.

**Concurrency safety:** The `acceptPlaybackAudio` volatile flag guards `onWsBinary()`, which is called from the WebSocket library's background task. It is cleared *before* `audio.stopSpeaker()` so any in-flight callbacks are rejected before the ring buffer is cleared — preventing a race between the background task and the main loop.

---

## Flashing the Firmware

### PlatformIO (recommended)

```bash
# Install PlatformIO CLI
pip install platformio

cd esp32_firmware

# Build
pio run

# Flash
pio run --target upload

# Open serial monitor
pio device monitor --baud 115200
```

All libraries are downloaded automatically on first build.

### Arduino IDE

1. Install **ESP32 board support** via Board Manager (URL: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`)
2. Install libraries via Library Manager:
   - WebSockets by Markus Sattler
   - Adafruit SSD1306
   - Adafruit GFX Library
   - ArduinoJson
   - FastLED
3. Open `esp32_firmware/src/main.cpp` (rename to `.ino` if needed)
4. Select board: **ESP32 Dev Module**, partition scheme: **Huge APP**
5. Upload speed: **921600**

---

## Serial Monitor Commands

Connect at **115200 baud**. Commands take effect immediately.

| Key | Action |
|-----|--------|
| `s` | Start listening (from IDLE or SPEAKING) |
| `e` | Stop listening and send to backend |
| `c` | Cancel — interrupt recording or playback |
| `r` | Restart ESP32 (`ESP.restart()`) |
| `h` or `?` | Print help + current state and buffer info |

Example session:

```
[Main] Setup complete, entering main loop

╔══════════════════════════════════════════╗
║       Serial Monitor Commands            ║
╠══════════════════════════════════════════╣
║  s + Enter  →  Start listening (record)  ║
║  e + Enter  →  Stop listening (process)  ║
║  c + Enter  →  Cancel / interrupt         ║
║  r + Enter  →  Reset ESP32               ║
║  BOOT btn   →  Tap=start, tap again=send ║
╚══════════════════════════════════════════╝

s
[Serial] >>> START LISTENING
[State] 0 → 2
[Mic] Peak amplitude: 3412 (gain=400)
e
[Serial] >>> STOP LISTENING → Processing...
[WS Recv] type=thinking data=
[WS Recv] type=transcript data=What time is it?
[WS Recv] type=speaking data=
[Main] Audio response complete
[Main] Echo cooldown complete, returning to IDLE
```

---

## LED Color Control

The WS2812B LED responds to voice commands. Tell the assistant to change the light color and the LLM appends a `[LED:colorname]` tag that the backend parses and forwards.

Supported colors:

| Say... | Color |
|--------|-------|
| "red" | Red |
| "green" | Green |
| "blue" | Blue |
| "white" | White |
| "yellow" | Yellow |
| "orange" | Orange |
| "purple" | Purple |
| "pink" | Pink |
| "cyan" | Cyan |
| "warm white" | Warm white (amber tint) |
| "off" | Off |

Example: *"Turn the light blue"* → assistant says *"Turning it blue."* and the LED changes instantly while TTS is still synthesizing.

The LED state persists until the next color command. It is not reset on reconnect.

---

## Troubleshooting

### No sound from microphone

- Check wiring — especially the SD (data), WS, and SCK pins.
- Open Serial Monitor and watch `[Mic] Peak amplitude`. If it shows 0 or near-zero, the mic is not producing data.
- Toggle the channel: change `I2S_CHANNEL_FMT_ONLY_LEFT` → `I2S_CHANNEL_FMT_ONLY_RIGHT` in `audio.h → beginMicrophone()`.
- Try increasing `micGain` in `audio.h` (default 400, try 600–800).

### No audio playback

- Check MAX98357A VIN is 5V (not 3.3V).
- Verify BCLK, LRC, DIN wiring against `config.h`.
- Watch Serial Monitor for `[Audio] Playback buffer overflow` — if the ring buffer fills up, audio is being dropped (unlikely on a single ESP32).

### WebSocket won't connect

- Confirm `WS_HOST` in `config.h` matches the PC's LAN IP (not `localhost`).
- Make sure the backend server is running (`python main.py`).
- Check that the firewall allows TCP 8765.
- Watch for `[WS] Disconnected` messages — the client retries every 3 seconds automatically.

### Display shows garbage / blank

- Verify SDA/SCL connections (GPIO 21 / 22).
- Check OLED I2C address — change `OLED_ADDR` in `config.h` from `0x3C` to `0x3D`.
- Confirm the display is 3.3V-compatible (most SSD1306 modules are).

### LED not responding to commands

- Confirm 5V on VCC (3.3V causes unreliable behavior).
- Add a 300Ω series resistor on the data line if not already present.
- Check `LED_COUNT` in `config.h` matches your strip.
- Watch Serial Monitor for `[LED] Set to rgb(...)` — if it appears, the firmware received the command and the issue is hardware.

### Transcription always empty / wrong

- Watch `[STT]` log lines on the PC backend for RMS level.
- If RMS < 0.001, the mic gain is too low — increase `micGain` in `audio.h`.
- Make sure `SAMPLE_RATE` in `config.h` matches `SAMPLE_RATE` in the backend `config.py` (both must be 16000).
