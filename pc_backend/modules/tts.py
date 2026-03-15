"""
Text-to-Speech module using pyttsx3 (OS built-in TTS).

Works on Windows (SAPI5), macOS, and Linux without model downloads or
external binaries. Audio is resampled to 16kHz mono to match the ESP32
speaker configuration.
"""
import os
import time
import wave
import tempfile
import numpy as np
import pyttsx3
import config


class TextToSpeech:
    def __init__(self):
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", 160)
        print("[TTS] Initialized (pyttsx3)")

    def synthesize(self, text: str) -> bytes:
        """
        Convert text to raw PCM audio (16kHz, 16-bit, mono).
        Returns bytes of PCM audio data.
        """
        if not text.strip():
            return b""

        print(f"[TTS] Synthesizing: \"{text[:80]}{'...' if len(text)>80 else ''}\"")
        start = time.time()

        # mkstemp creates the file atomically (no TOCTOU race between
        # generating the path and pyttsx3 opening it).  Close the fd
        # immediately — pyttsx3 will reopen the file by path itself.
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)
        try:
            self._engine.save_to_file(text, tmp_path)
            self._engine.runAndWait()

            with wave.open(tmp_path, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                src_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                src_width = wf.getsampwidth()

            if src_width != 2:
                raise ValueError(
                    f"pyttsx3 produced {src_width * 8}-bit audio; expected 16-bit. "
                    "Check your OS TTS engine settings."
                )

            # Mix stereo → mono if needed
            if n_channels == 2:
                samples = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
                raw = samples.mean(axis=1).astype(np.int16).tobytes()

            pcm_data = self._resample(raw, src_rate, config.SAMPLE_RATE)
        except Exception as e:
            print(f"[TTS] Error: {e}")
            return b""
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        elapsed = time.time() - start
        duration = len(pcm_data) / (config.SAMPLE_RATE * config.SAMPLE_WIDTH)
        print(f"[TTS] Done ({elapsed:.2f}s) → {duration:.1f}s of audio")
        return pcm_data

    def _resample(self, pcm_data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """Resample 16-bit PCM from src_rate to dst_rate using linear interpolation."""
        if src_rate == dst_rate:
            return pcm_data

        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
        new_length = int(len(samples) * dst_rate / src_rate)
        x_old = np.linspace(0, 1, len(samples))
        x_new = np.linspace(0, 1, new_length)
        resampled = np.interp(x_new, x_old, samples)
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

    def synthesize_chunks(self, text: str, chunk_size: int = config.AUDIO_STREAM_CHUNK):
        """
        Generator: synthesize text and yield PCM audio in chunks.
        Used for streaming audio back to the ESP32.
        """
        pcm_data = self.synthesize(text)
        if not pcm_data:
            return

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
