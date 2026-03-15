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
        # Incremented on every new start_listening.  Each process_utterance()
        # captures the value at call time; if it changes, the pipeline is stale
        # and aborts at the next checkpoint — no flag-reset race possible.
        self._session_id = 0

    def new_session(self):
        """Start a fresh listen/process cycle, invalidating any running pipeline."""
        self._session_id += 1
        self.is_cancelled = False
        self.is_listening = True

    async def send_json(self, msg_type: str, **kwargs):
        """Send a JSON message to the ESP32."""
        data = {"type": msg_type, **kwargs}
        await self.ws.send_text(json.dumps(data))

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
        Launched as an asyncio Task so the WebSocket receive loop keeps
        running concurrently — cancel/start messages are handled in real time.
        """
        pipeline_start = time.time()
        my_session_id = self._session_id  # Snapshot — any change means we're stale

        def stale() -> bool:
            """True if a newer session has started or an explicit cancel arrived."""
            return self.is_cancelled or self._session_id != my_session_id

        # ── Step 1: Speech to Text ──────────────────────
        print("\n[Pipeline] Step 1: Transcribing speech...")
        await self.send_json("thinking")

        # Run in a thread — Whisper can take 1–3 s on CPU and must not block
        # the event loop (which would prevent receiving cancel messages).
        text = await asyncio.to_thread(self.stt.transcribe)

        if not text:
            print("[Pipeline] No speech detected")
            if not stale():
                await self.send_json("error", text="I didn't hear anything. Try again?")
            return

        await self.send_json("transcript", text=text)

        if stale():
            print("[Pipeline] Cancelled after STT")
            return

        # ── Step 2: LLM Response ────────────────────────
        print("[Pipeline] Step 2: Getting LLM response...")
        llm_start = time.time()
        try:
            response_text = await asyncio.wait_for(
                asyncio.to_thread(self.llm.chat, text),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            print("[Pipeline] LLM timed out after 30s")
            if not stale():
                await self.send_json("error", text="Response took too long. Please try again.")
            return
        except asyncio.CancelledError:
            raise  # Propagate hard task cancellation

        llm_elapsed = time.time() - llm_start
        print(f"[Pipeline] LLM took {llm_elapsed:.2f}s")

        if stale():
            print("[Pipeline] Cancelled after LLM")
            return

        await self.send_json("response", text=response_text)

        # ── Step 3: Text to Speech ──────────────────────
        print("[Pipeline] Step 3: Synthesizing speech...")
        await self.send_json("speaking")

        tts_start = time.time()

        # pyttsx3 synthesis runs in a thread (see tts.py for why a fresh engine
        # is created each call — reuse deadlocks on Linux).
        pcm_data = await asyncio.to_thread(self.tts.synthesize, response_text)
        if not pcm_data:
            print("[Pipeline] TTS returned no audio")
            if not stale():
                await self.send_json("error", text="Sorry, I couldn't generate a spoken reply.")
            return

        chunks_sent = 0
        offset = 0
        chunk_size = config.AUDIO_STREAM_CHUNK

        while offset < len(pcm_data):
            if stale():
                print("[Pipeline] Cancelled during TTS streaming")
                break

            end = min(offset + chunk_size, len(pcm_data))
            await self.ws.send_bytes(pcm_data[offset:end])
            chunks_sent += 1
            offset = end

            # Yield every 10 chunks so the event loop can process incoming frames
            if chunks_sent % 10 == 0:
                await asyncio.sleep(0)

        tts_elapsed = time.time() - tts_start
        print(f"[Pipeline] TTS streaming took {tts_elapsed:.2f}s ({chunks_sent} chunks)")

        # Signal end of audio only if this pipeline is still the active one.
        # A stale pipeline must not send audio_end — the ESP32 may have already
        # returned to IDLE (via cancel) and the flag would corrupt the next session.
        if not stale():
            await self.send_json("audio_end")

        total = time.time() - pipeline_start
        print(f"\n[Pipeline] ✓ Total round-trip: {total:.2f}s\n")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    WebSocket endpoint for ESP32 connections.
    Each connected ESP32 gets its own VoiceSession.

    The pipeline (STT→LLM→TTS) runs as a concurrent asyncio Task so this
    receive loop is never blocked.  Cancel and start_listening messages are
    therefore handled in real time rather than queued until the pipeline ends.
    """
    await ws.accept()
    client_host = ws.client.host if ws.client else "unknown"
    print(f"\n[Server] ESP32 connected from {client_host}")

    session = VoiceSession(ws)
    pipeline_task: asyncio.Task | None = None

    try:
        while True:
            message = await ws.receive()

            # Starlette delivers close frames as a dict with type "websocket.disconnect"
            if message.get("type") == "websocket.disconnect":
                print(f"[Server] ESP32 disconnected ({client_host})")
                break

            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "")

                    if msg_type == "start_listening":
                        print("\n[Session] ▶ Start listening")
                        # new_session() increments _session_id — any running
                        # pipeline's stale() check will return True at its next
                        # checkpoint and exit without sending further messages.
                        session.new_session()
                        session.stt.clear_buffer()

                    elif msg_type == "stop_listening":
                        print("[Session] ⏹ Stop listening")
                        session.is_listening = False
                        # Launch pipeline concurrently; receive loop keeps running
                        pipeline_task = asyncio.create_task(session.process_utterance())

                    elif msg_type == "cancel":
                        print("[Session] ✖ Cancel requested")
                        session.is_cancelled = True

                except json.JSONDecodeError:
                    print(f"[Server] Invalid JSON: {message['text'][:100]}")
                except Exception as e:
                    print(f"[Server] Error handling text message: {e}")

            elif "bytes" in message:
                try:
                    session.handle_audio_data(message["bytes"])
                except Exception as e:
                    print(f"[Server] Error handling audio data: {e}")

    except WebSocketDisconnect:
        print(f"[Server] ESP32 disconnected ({client_host})")
    except RuntimeError as e:
        # Starlette raises RuntimeError("Cannot call 'receive' once a disconnect
        # message has been received") if the loop iterates after a close frame.
        if "disconnect" in str(e).lower():
            print(f"[Server] ESP32 disconnected ({client_host})")
        else:
            print(f"[Server] Runtime error: {e}")
    except Exception as e:
        print(f"[Server] Error: {e}")
    finally:
        # Signal and clean up any in-flight pipeline
        session.is_cancelled = True
        if pipeline_task and not pipeline_task.done():
            pipeline_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(pipeline_task), timeout=2.0)
            except Exception:
                pass
        print(f"[Server] Session ended ({client_host})")


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
