# Development Guide

## Debugging Strategies

### ESP32 Debugging

**Serial Monitor**: Open at 115200 baud. Every module logs prefixed messages:
- `[WiFi]` — Connection status
- `[WS]` — WebSocket events
- `[Audio]` — Mic/speaker I2S operations
- `[OLED]` — Display initialization
- `[State]` — State machine transitions
- `[Button]` — Push-to-talk events
- `[Main]` — Pipeline coordination

**Common ESP32 Issues:**

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No audio captured | Mic wiring wrong, L/R pin not grounded | Check INMP441 L/R → GND |
| Audio is very quiet | INMP441 gain too low | Increase `micGain` in audio.h (try 300-500) |
| Speaker pops/clicks | DMA buffer underrun | Increase `dma_buf_count` to 16 |
| WS disconnects | WiFi interference, server crash | Check signal strength, server logs |
| OLED blank | I2C address wrong | Try 0x3D instead of 0x3C |
| Boot loop | I2S pin conflict | Verify no pin overlaps in config.h |
| Guru Meditation | Stack overflow | Increase stack size or reduce buffer sizes |

**I2S Signal Verification:**
Connect an oscilloscope or logic analyzer to SCK/WS/SD pins to verify:
- SCK should run at SAMPLE_RATE × BITS × 2 = 16000 × 16 × 2 = 512kHz
- WS should toggle at SAMPLE_RATE = 16kHz
- SD should have data during left channel (L/R = GND)

### PC Backend Debugging

**Module-by-module testing** (most important — always test individually first):
```bash
cd pc_backend
source venv/bin/activate

# Test each module in isolation
python -m tests.test_modules stt       # Does Whisper load?
python -m tests.test_modules llm       # Does Gemini respond?
python -m tests.test_modules tts       # Does Piper synthesize?
python -m tests.test_modules pipeline  # Does the chain work?
```

**WebSocket testing without ESP32:**
```bash
# Terminal 1: Start server
python main.py

# Terminal 2: Run simulated client
python tests/test_ws_client.py

# Check audio_cache/test_response.wav with any audio player
```

**Audio inspection:**
```bash
# Install sox for command-line audio tools
sudo apt install sox

# Play raw PCM
play -r 16000 -b 16 -e signed -c 1 audio_cache/test_response.wav

# Convert raw PCM to WAV
sox -r 16000 -b 16 -e signed -c 1 -t raw input.raw output.wav
```

---

## Latency Optimization

### Quick Wins (do these first)

1. **Use `base.en` Whisper model** — already set as default. The `.en` suffix means
   English-only which is faster than multilingual. `tiny.en` is even faster but
   less accurate.

2. **Keep LLM responses short** — the system prompt already asks for 1-3 sentences.
   Shorter text = less TTS processing = faster response.

3. **Use Piper binary, not Python package** — the native binary is 2-3x faster.
   The setup script downloads it automatically.

4. **Place PC on same subnet as ESP32** — minimize network hops. Wired ethernet
   on the PC side is ideal.

### Advanced Optimizations

**GPU Acceleration for STT:**
```bash
# Install CTranslate2 with CUDA
pip install ctranslate2 --extra-index-url https://download.pytorch.org/whl/cu118

# Update .env
STT_DEVICE=cuda
STT_COMPUTE_TYPE=float16
```
This cuts STT time from ~300ms to ~80ms on a modern NVIDIA GPU.

**Streaming LLM → TTS Pipeline:**
Instead of waiting for the full LLM response before starting TTS, you can
process sentence by sentence:

```python
# In VoiceSession.process_utterance(), replace the LLM+TTS steps with:
async def process_utterance_streaming(self):
    # ... STT step same as before ...
    
    sentence_buffer = ""
    async for chunk in self.llm.chat_stream(text):
        sentence_buffer += chunk
        
        # Check for sentence boundaries
        for sep in ['. ', '! ', '? ', '\n']:
            if sep in sentence_buffer:
                sentence, sentence_buffer = sentence_buffer.rsplit(sep, 1)
                sentence += sep.strip()
                
                # Synthesize and stream this sentence immediately
                for audio_chunk in self.tts.synthesize_chunks(sentence):
                    await self.ws.send_bytes(audio_chunk)
    
    # Don't forget the last fragment
    if sentence_buffer.strip():
        for audio_chunk in self.tts.synthesize_chunks(sentence_buffer):
            await self.ws.send_bytes(audio_chunk)
```

This can reduce perceived latency by 500ms-1s since audio starts playing
while the LLM is still generating.

**ESP32 Audio Buffer Tuning:**
- Increase `dma_buf_count` to 16 for smoother playback
- Decrease `AUDIO_CHUNK_SAMPLES` to 256 for lower mic-capture latency (at cost of more network overhead)

---

## Extension Ideas

### 1. Wake Word Detection

Add "Hey Assistant" detection so you don't need the button:

**On ESP32 (lightweight):**
Use the [ESP-SR](https://github.com/espressif/esp-sr) library which runs
wake word detection directly on the ESP32 with minimal latency:

```cpp
// In main.cpp, replace button-based trigger:
#include "esp_wn_iface.h"
#include "esp_wn_models.h"

// Initialize wake word engine in setup()
esp_wn_handle_t wakenet = esp_wn_iface.create(model_name, DET_MODE_90);

// In loop(), continuously feed mic audio to wake word detector
// When detected, transition to STATE_LISTENING automatically
```

**On PC (more accurate):**
Use [OpenWakeWord](https://github.com/dscripka/openWakeWord) or [Porcupine](https://picovoice.ai/platform/porcupine/):
- Stream mic audio continuously to PC
- PC runs wake word detection
- On detection, PC sends `{"type":"wake"}` to ESP32
- ESP32 transitions to LISTENING

### 2. Conversation Memory with RAG

Add persistent memory so the assistant remembers across sessions:

```python
# pc_backend/modules/memory.py
import chromadb

class ConversationMemory:
    def __init__(self):
        self.client = chromadb.PersistentClient(path="./memory_db")
        self.collection = self.client.get_or_create_collection("conversations")
    
    def store(self, user_text: str, assistant_text: str):
        self.collection.add(
            documents=[f"User: {user_text}\nAssistant: {assistant_text}"],
            ids=[f"turn_{time.time()}"]
        )
    
    def recall(self, query: str, n=3) -> list[str]:
        results = self.collection.query(query_texts=[query], n_results=n)
        return results["documents"][0]
```

Then inject recalled context into the Gemini system prompt.

### 3. Interruption Support

Already partially implemented — pressing the button during SPEAKING sends
a cancel message. To make it more responsive:

- **ESP32**: The `handleButton()` already calls `audio.stopSpeaker()` and
  sends `cancel`. This stops playback immediately.
- **PC**: Set `self.is_cancelled = True` which breaks the TTS streaming loop.

For hands-free interruption, combine with wake word: if the wake word is
detected during SPEAKING, treat it as an interrupt.

### 4. Multi-Language Support

- Change `STT_MODEL_SIZE` from `base.en` to `base` (multilingual)
- Remove `language="en"` from the Whisper transcribe call (auto-detect)
- Download a different Piper voice model for the target language
- Update the Gemini system prompt to respond in the detected language

### 5. Local LLM (No Internet Required)

Replace Gemini with a local model using [Ollama](https://ollama.ai):

```python
# pc_backend/modules/llm_local.py
import requests

class LocalLLM:
    def chat(self, text: str) -> str:
        response = requests.post("http://localhost:11434/api/generate", json={
            "model": "llama3.2:3b",  # or any model
            "prompt": text,
            "stream": False,
        })
        return response.json()["response"]
```

### 6. Audio Feedback / Sound Effects

Add confirmation sounds on the ESP32 for better UX:
- Short beep when recording starts
- Different tone when recording stops
- Error sound on failures

Store these as const arrays in flash:
```cpp
// Short 200ms beep at 800Hz
const int16_t BEEP_START[] PROGMEM = { ... };
```

---

## Production Hardening Checklist

- [ ] Add OTA (Over-the-Air) updates to ESP32 firmware
- [ ] Implement WiFi reconnection with exponential backoff
- [ ] Add WebSocket authentication (token in connection URL)
- [ ] Rate-limit API calls to Gemini
- [ ] Add audio level metering (skip STT if audio is silence)
- [ ] Implement proper error recovery in all states
- [ ] Add health monitoring (uptime, error counts, latency stats)
- [ ] Test with multiple simultaneous ESP32 clients
- [ ] Add TLS/WSS for encrypted communication
- [ ] Battery monitoring if running on LiPo
