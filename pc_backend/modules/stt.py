"""
Speech-to-Text module using Faster-Whisper.

Accumulates raw PCM audio chunks, then transcribes on demand.
Uses CTranslate2 for fast inference — works on CPU or GPU.
"""
import io
import time
import numpy as np
from faster_whisper import WhisperModel
import config

class SpeechToText:
    def __init__(self):
        print(f"[STT] Loading Faster-Whisper model: {config.STT_MODEL_SIZE}")
        print(f"[STT] Device: {config.STT_DEVICE}, Compute: {config.STT_COMPUTE_TYPE}")

        self.model = WhisperModel(
            config.STT_MODEL_SIZE,
            device=config.STT_DEVICE,
            compute_type=config.STT_COMPUTE_TYPE,
        )
        print("[STT] Model loaded successfully")

        # Buffer to accumulate audio chunks during listening
        self._audio_chunks: list[bytes] = []

    def add_audio_chunk(self, chunk: bytes):
        """Add a raw PCM audio chunk (16kHz, 16-bit, mono)."""
        self._audio_chunks.append(chunk)

    def get_buffer_duration(self) -> float:
        """Return the current buffer duration in seconds."""
        total_bytes = sum(len(c) for c in self._audio_chunks)
        return total_bytes / (config.SAMPLE_RATE * config.SAMPLE_WIDTH)

    def clear_buffer(self):
        """Clear the audio buffer."""
        self._audio_chunks.clear()

    def transcribe(self) -> str:
        """
        Transcribe accumulated audio buffer.
        Returns the transcribed text, or empty string if nothing detected.
        Clears the buffer after transcription.
        """
        if not self._audio_chunks:
            return ""

        # Combine all chunks into one numpy array
        raw_audio = b"".join(self._audio_chunks)
        self._audio_chunks.clear()

        if len(raw_audio) < config.SAMPLE_RATE * config.SAMPLE_WIDTH * 0.3:
            # Less than 0.3 seconds of audio — skip
            print("[STT] Audio too short, skipping")
            return ""

        # Convert to float32 numpy array (Whisper expects float32 in [-1, 1])
        audio_np = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0

        print(f"[STT] Transcribing {len(audio_np)/config.SAMPLE_RATE:.1f}s of audio...")
        start = time.time()

        segments, info = self.model.transcribe(
            audio_np,
            language="en",
            beam_size=3,            # Lower = faster, higher = more accurate
            best_of=1,
            temperature=0.0,        # Greedy decoding for speed
            condition_on_previous_text=False,
            vad_filter=True,         # Filter out silence
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=200,
            ),
        )

        # Collect all segment texts
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        text = " ".join(text_parts).strip()
        elapsed = time.time() - start
        print(f"[STT] Result ({elapsed:.2f}s): \"{text}\"")

        return text


# Singleton instance
_instance = None

def get_stt() -> SpeechToText:
    global _instance
    if _instance is None:
        _instance = SpeechToText()
    return _instance
