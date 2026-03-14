"""
Text-to-Speech module using Piper TTS.

Piper is a fast, local neural TTS engine. It outputs 22050Hz audio which
we resample to 16000Hz to match the ESP32 speaker configuration.

If Piper is not installed, falls back to a simpler approach using
the piper-tts Python package.
"""
import io
import time
import struct
import subprocess
import shutil
import numpy as np
from pathlib import Path
import config


class TextToSpeech:
    def __init__(self):
        self._piper_binary = self._find_piper_binary()
        self._model_path = Path(config.PIPER_MODEL_PATH)

        if not self._model_path.exists():
            print(f"[TTS] WARNING: Piper model not found at {self._model_path}")
            print("[TTS] Download instructions:")
            print("  mkdir -p models && cd models")
            print("  wget https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                  "en/en_US/amy/medium/en_US-amy-medium.onnx")
            print("  wget https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                  "en/en_US/amy/medium/en_US-amy-medium.onnx.json")
            self._use_piper_python = True
        else:
            self._use_piper_python = False

        if self._piper_binary:
            print(f"[TTS] Using Piper binary: {self._piper_binary}")
        else:
            print("[TTS] Piper binary not found, using piper-tts Python package")
            self._use_piper_python = True

        if self._use_piper_python:
            try:
                from piper import PiperVoice
                self._piper_voice = PiperVoice.load(str(self._model_path))
                print("[TTS] Loaded Piper voice via Python package")
            except Exception as e:
                print(f"[TTS] Could not load Piper Python package: {e}")
                print("[TTS] Will use subprocess fallback")
                self._piper_voice = None

        print("[TTS] Initialized")

    def _find_piper_binary(self) -> str | None:
        """Look for the piper binary in common locations."""
        # Check models dir first (downloaded alongside models)
        local_piper = config.MODELS_DIR / "piper" / "piper"
        if local_piper.exists():
            return str(local_piper)

        # Check PATH
        piper_path = shutil.which("piper")
        if piper_path:
            return piper_path

        return None

    def synthesize(self, text: str) -> bytes:
        """
        Convert text to raw PCM audio (16kHz, 16-bit, mono).
        Returns bytes of PCM audio data.
        """
        if not text.strip():
            return b""

        print(f"[TTS] Synthesizing: \"{text[:80]}{'...' if len(text)>80 else ''}\"")
        start = time.time()

        try:
            if self._use_piper_python and self._piper_voice:
                pcm_data = self._synthesize_python(text)
            elif self._piper_binary:
                pcm_data = self._synthesize_binary(text)
            else:
                print("[TTS] No TTS engine available!")
                return b""
        except Exception as e:
            print(f"[TTS] Synthesis error: {e}")
            return b""

        elapsed = time.time() - start
        duration = len(pcm_data) / (config.SAMPLE_RATE * config.SAMPLE_WIDTH)
        print(f"[TTS] Done ({elapsed:.2f}s) → {duration:.1f}s of audio")

        return pcm_data

    def _synthesize_python(self, text: str) -> bytes:
        """Synthesize using piper-tts Python package."""
        from piper import PiperVoice

        # Piper outputs to a WAV-like stream
        audio_stream = io.BytesIO()

        # Use synthesize_stream_raw for raw PCM
        raw_samples = []
        for audio_chunk in self._piper_voice.synthesize_stream_raw(text):
            raw_samples.append(audio_chunk)

        raw_audio = b"".join(raw_samples)

        # Piper outputs at PIPER_SAMPLE_RATE (22050), resample to 16000
        return self._resample(raw_audio, config.PIPER_SAMPLE_RATE, config.SAMPLE_RATE)

    def _synthesize_binary(self, text: str) -> bytes:
        """Synthesize using piper command-line binary."""
        cmd = [
            self._piper_binary,
            "--model", str(self._model_path),
            "--output_raw",
            "--speaker", str(config.PIPER_SPEAKER_ID),
        ]

        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )

        if proc.returncode != 0:
            print(f"[TTS] Piper error: {proc.stderr.decode()}")
            return b""

        raw_audio = proc.stdout
        return self._resample(raw_audio, config.PIPER_SAMPLE_RATE, config.SAMPLE_RATE)

    def _resample(self, pcm_data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """
        Resample PCM audio from src_rate to dst_rate.
        Input/output: raw 16-bit signed PCM bytes.
        Uses linear interpolation for speed.
        """
        if src_rate == dst_rate:
            return pcm_data

        # Convert to numpy
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)

        # Calculate resampled length
        duration = len(samples) / src_rate
        new_length = int(duration * dst_rate)

        # Linear interpolation resampling
        x_old = np.linspace(0, 1, len(samples))
        x_new = np.linspace(0, 1, new_length)
        resampled = np.interp(x_new, x_old, samples)

        # Convert back to int16
        resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
        return resampled.tobytes()

    def synthesize_chunks(self, text: str, chunk_size: int = config.AUDIO_STREAM_CHUNK):
        """
        Generator: synthesize text and yield PCM audio in chunks.
        Used for streaming audio back to the ESP32.
        """
        pcm_data = self.synthesize(text)
        if not pcm_data:
            return

        # Yield in fixed-size chunks
        offset = 0
        while offset < len(pcm_data):
            end = min(offset + chunk_size, len(pcm_data))
            yield pcm_data[offset:end]
            offset = end


# Singleton
_instance = None

def get_tts() -> TextToSpeech:
    global _instance
    if _instance is None:
        _instance = TextToSpeech()
    return _instance
