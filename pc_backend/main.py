"""
ESP32 Voice Assistant — PC Backend Server

WebSocket server that orchestrates the full voice pipeline:
  1. Receives raw PCM audio from ESP32
  2. Transcribes speech with Faster-Whisper
  3. Gets a response from Ollama (local LLM)
  4. Converts response to speech with pyttsx3
  5. Streams audio back to ESP32

Run:
    python main.py
"""
import asyncio
import json
import time
import signal
import sys

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

import config
from modules.stt import get_stt
from modules.llm import get_llm
from modules.tts import get_tts

app = FastAPI(title="ESP32 Voice Assistant Backend")


class VoiceSession:
    """
    Manages one connected ESP32 device's voice session.
    Handles the state machine: listening → transcribing → thinking → speaking.
    """

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.stt = get_stt()
        self.llm = get_llm()
        self.tts = get_tts()
        self.is_listening = False
        self.is_cancelled = False

    async def send_json(self, msg_type: str, **kwargs):
        """Send a JSON message to the ESP32."""
        data = {"type": msg_type, **kwargs}
        await self.ws.send_text(json.dumps(data))

    async def handle_text_message(self, data: dict):
        """Handle a JSON control message from the ESP32."""
        msg_type = data.get("type", "")

        if msg_type == "start_listening":
            print("\n[Session] ▶ Start listening")
            self.is_listening = True
            self.is_cancelled = False
            self.stt.clear_buffer()

        elif msg_type == "stop_listening":
            print("[Session] ⏹ Stop listening")
            self.is_listening = False
            # Process the captured audio
            await self.process_utterance()

        elif msg_type == "cancel":
            print("[Session] ✖ Cancel requested")
            self.is_cancelled = True

    def handle_audio_data(self, data: bytes):
        """Handle binary audio data from the ESP32 microphone."""
        if self.is_listening:
            # Cap at 60 seconds to prevent unbounded memory growth
            if self.stt.get_buffer_duration() < 60.0:
                self.stt.add_audio_chunk(data)
            else:
                print("[Session] Max audio buffer (60s) reached, dropping chunk")

    async def process_utterance(self):
        """
        Full pipeline: STT → LLM → TTS → Stream back to ESP32.
        This is called after the user releases the push-to-talk button.
        """
        pipeline_start = time.time()

        # ── Step 1: Speech to Text ──────────────────────
        print("\n[Pipeline] Step 1: Transcribing speech...")
        await self.send_json("thinking")

        text = self.stt.transcribe()

        if not text:
            print("[Pipeline] No speech detected")
            await self.send_json("error", text="I didn't hear anything. Try again?")
            return

        # Send transcript to ESP32 for display
        await self.send_json("transcript", text=text)

        if self.is_cancelled:
            print("[Pipeline] Cancelled after STT")
            return

        # ── Step 2: LLM Response ────────────────────────
        print("[Pipeline] Step 2: Getting LLM response...")
        llm_start = time.time()
        try:
            # Run blocking LLM call in a thread to avoid blocking the event loop
            response_text = await asyncio.wait_for(
                asyncio.to_thread(self.llm.chat, text),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            print("[Pipeline] LLM timed out after 30s")
            await self.send_json("error", text="Response took too long. Please try again.")
            return
        llm_elapsed = time.time() - llm_start
        print(f"[Pipeline] LLM took {llm_elapsed:.2f}s")

        if self.is_cancelled:
            print("[Pipeline] Cancelled after LLM")
            return

        # Send response text to ESP32
        await self.send_json("response", text=response_text)

        # ── Step 3: Text to Speech ──────────────────────
        print("[Pipeline] Step 3: Synthesizing speech...")
        await self.send_json("speaking")

        tts_start = time.time()
        chunks_sent = 0

        for audio_chunk in self.tts.synthesize_chunks(response_text):
            if self.is_cancelled:
                print("[Pipeline] Cancelled during TTS streaming")
                break

            await self.ws.send_bytes(audio_chunk)
            chunks_sent += 1

            # Small yield to keep the event loop responsive
            # and allow receiving cancel messages
            if chunks_sent % 10 == 0:
                await asyncio.sleep(0.001)

        tts_elapsed = time.time() - tts_start
        print(f"[Pipeline] TTS streaming took {tts_elapsed:.2f}s ({chunks_sent} chunks)")

        # Signal end of audio — skip if cancelled; ESP32 already returned to IDLE via
        # its own cancelAction() and sending a stale audio_end would set audioEndReceived
        # while the device is idle, confusing the next SPEAKING→IDLE transition.
        if not self.is_cancelled:
            await self.send_json("audio_end")

        total = time.time() - pipeline_start
        print(f"\n[Pipeline] ✓ Total round-trip: {total:.2f}s\n")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    WebSocket endpoint for ESP32 connections.
    Each connected ESP32 gets its own VoiceSession.
    """
    await ws.accept()
    client_host = ws.client.host if ws.client else "unknown"
    print(f"\n[Server] ESP32 connected from {client_host}")

    session = VoiceSession(ws)

    try:
        while True:
            message = await ws.receive()

            if "text" in message:
                # JSON control message
                try:
                    data = json.loads(message["text"])
                    await session.handle_text_message(data)
                except json.JSONDecodeError:
                    print(f"[Server] Invalid JSON: {message['text'][:100]}")
                except Exception as e:
                    print(f"[Server] Error handling text message: {e}")

            elif "bytes" in message:
                # Binary audio data
                try:
                    session.handle_audio_data(message["bytes"])
                except Exception as e:
                    print(f"[Server] Error handling audio data: {e}")

    except WebSocketDisconnect:
        print(f"[Server] ESP32 disconnected ({client_host})")
    except Exception as e:
        print(f"[Server] Error: {e}")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "ok",
        "stt_model": config.STT_MODEL_SIZE,
        "llm_model": config.OLLAMA_MODEL,
        "llm_url": config.OLLAMA_URL,
        "tts_engine": "pyttsx3",
    }


def main():
    print("=" * 60)
    print("  ESP32 Voice Assistant — PC Backend")
    print("=" * 60)
    print(f"  WebSocket:  ws://{config.WS_HOST}:{config.WS_PORT}/ws")
    print(f"  STT Model:  {config.STT_MODEL_SIZE} ({config.STT_DEVICE})")
    print(f"  LLM:        {config.OLLAMA_MODEL} via {config.OLLAMA_URL}")
    print(f"  TTS:        pyttsx3 (OS built-in)")
    print(f"  Audio:      {config.SAMPLE_RATE}Hz, {config.SAMPLE_WIDTH*8}-bit, mono")
    print("=" * 60)

    # Pre-load models at startup (so first request is fast)
    print("\n[Startup] Pre-loading models...")
    try:
        get_stt()
        print("[Startup] ✓ STT ready")
    except Exception as e:
        print(f"[Startup] ✗ STT error: {e}")

    try:
        get_llm()
        print("[Startup] ✓ LLM ready")
    except Exception as e:
        print(f"[Startup] ✗ LLM error: {e}")

    try:
        get_tts()
        print("[Startup] ✓ TTS ready")
    except Exception as e:
        print(f"[Startup] ✗ TTS error: {e}")

    print("\n[Server] Starting... Press Ctrl+C to stop.\n")

    uvicorn.run(
        app,
        host=config.WS_HOST,
        port=config.WS_PORT,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


if __name__ == "__main__":
    main()
