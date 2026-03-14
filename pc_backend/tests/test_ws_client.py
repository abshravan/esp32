"""
WebSocket test client — simulates an ESP32 device.

Connects to the backend, sends pre-recorded or synthetic audio,
and receives the response. Useful for testing without hardware.

Usage:
    python tests/test_ws_client.py                     # Send synthetic audio
    python tests/test_ws_client.py recording.raw       # Send a real recording
    python tests/test_ws_client.py --text "Hello"      # Skip STT, test LLM+TTS
"""
import asyncio
import json
import struct
import math
import sys
import wave
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
import config


async def send_audio_file(ws, filepath: str):
    """Send a raw PCM file in chunks."""
    chunk_size = 1024
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            await ws.send(chunk)
            await asyncio.sleep(0.03)  # Simulate real-time ~32ms chunks


async def send_synthetic_audio(ws, duration_s=2.0):
    """Send synthetic audio that won't transcribe meaningfully."""
    import numpy as np

    sample_rate = 16000
    num_samples = int(duration_s * sample_rate)
    chunk_samples = 512

    # Generate random noise (won't transcribe, but tests the pipeline)
    print(f"[Test] Sending {duration_s}s of synthetic audio...")

    for i in range(0, num_samples, chunk_samples):
        remaining = min(chunk_samples, num_samples - i)
        # Low-amplitude noise
        samples = (np.random.randn(remaining) * 1000).astype("<i2")
        await ws.send(samples.tobytes())
        await asyncio.sleep(chunk_samples / sample_rate)


async def test_session():
    """Run a test session against the backend."""
    uri = f"ws://localhost:{config.WS_PORT}/ws"
    print(f"[Test] Connecting to {uri}")

    received_audio = bytearray()

    async with websockets.connect(uri) as ws:
        print("[Test] Connected!")

        # Start listening
        await ws.send(json.dumps({"type": "start_listening"}))
        print("[Test] Sent: start_listening")

        # Send audio
        if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
            await send_audio_file(ws, sys.argv[1])
        else:
            await send_synthetic_audio(ws, 2.0)

        # Stop listening
        await ws.send(json.dumps({"type": "stop_listening"}))
        print("[Test] Sent: stop_listening")

        # Receive responses
        print("[Test] Waiting for response...")
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)

                if isinstance(msg, str):
                    data = json.loads(msg)
                    msg_type = data.get("type", "")
                    print(f"[Test] Received: {data}")

                    if msg_type == "audio_end":
                        print("[Test] Audio stream complete")
                        break
                    elif msg_type == "error":
                        print(f"[Test] Server error: {data.get('text', '')}")
                        break
                else:
                    received_audio.extend(msg)
                    print(f"[Test] Received audio chunk: {len(msg)} bytes "
                          f"(total: {len(received_audio)})")

        except asyncio.TimeoutError:
            print("[Test] Timeout waiting for response")

    # Save received audio
    if received_audio:
        out_path = "audio_cache/test_response.wav"
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(bytes(received_audio))
        duration = len(received_audio) / (16000 * 2)
        print(f"\n[Test] Saved {duration:.1f}s response audio to {out_path}")
    else:
        print("\n[Test] No audio received")


if __name__ == "__main__":
    asyncio.run(test_session())
