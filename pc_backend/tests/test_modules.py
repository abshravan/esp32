"""
Backend module tests — run each component independently.

Usage:
    python -m tests.test_modules          # Run all tests
    python -m tests.test_modules stt      # Test STT only
    python -m tests.test_modules llm      # Test LLM only
    python -m tests.test_modules tts      # Test TTS only
    python -m tests.test_modules pipeline # Test full pipeline
"""
import sys
import os
import time
import struct
import math
import numpy as np

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_test_audio(duration_s=2.0, frequency=440, sample_rate=16000):
    """Generate a sine wave test tone as raw PCM bytes."""
    num_samples = int(duration_s * sample_rate)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        value = int(16000 * math.sin(2 * math.pi * frequency * t))
        samples.append(struct.pack("<h", value))
    return b"".join(samples)


def generate_speech_like_audio(duration_s=2.0, sample_rate=16000):
    """
    Generate audio that vaguely resembles speech patterns
    (mix of frequencies, amplitude modulation).
    """
    num_samples = int(duration_s * sample_rate)
    t = np.arange(num_samples) / sample_rate

    # Fundamental + harmonics (like a vowel)
    signal = (
        0.5 * np.sin(2 * np.pi * 150 * t) +    # F0
        0.3 * np.sin(2 * np.pi * 300 * t) +    # Harmonic
        0.2 * np.sin(2 * np.pi * 700 * t) +    # Formant 1
        0.1 * np.sin(2 * np.pi * 1200 * t)     # Formant 2
    )

    # Amplitude envelope (speech-like bursts)
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    signal = signal * envelope * 16000

    pcm = np.clip(signal, -32768, 32767).astype(np.int16)
    return pcm.tobytes()


def test_stt():
    """Test Speech-to-Text module."""
    print("\n" + "=" * 50)
    print("Testing STT (Faster-Whisper)")
    print("=" * 50)

    from modules.stt import get_stt
    stt = get_stt()

    # Feed it some audio (won't produce meaningful text, but tests the pipeline)
    audio = generate_speech_like_audio(2.0)
    chunk_size = 1024
    chunks_fed = 0

    for i in range(0, len(audio), chunk_size):
        stt.add_audio_chunk(audio[i:i + chunk_size])
        chunks_fed += 1

    print(f"Fed {chunks_fed} chunks ({stt.get_buffer_duration():.1f}s)")

    result = stt.transcribe()
    print(f"Transcription result: \"{result}\"")
    print("✓ STT module works (transcription may be empty/gibberish with synthetic audio)")
    return True


def test_llm():
    """Test LLM module."""
    print("\n" + "=" * 50)
    print("Testing LLM (Google Gemini)")
    print("=" * 50)

    from modules.llm import get_llm
    llm = get_llm()

    # Simple test
    start = time.time()
    response = llm.chat("Hello! What's 2 plus 2?")
    elapsed = time.time() - start

    print(f"Response: \"{response}\"")
    print(f"Latency: {elapsed:.2f}s")
    print(f"History: {llm.get_history_summary()}")

    # Test memory
    response2 = llm.chat("What did I just ask you?")
    print(f"Memory test: \"{response2}\"")

    assert len(response) > 0, "Empty response from LLM"
    print("✓ LLM module works")
    return True


def test_tts():
    """Test TTS module."""
    print("\n" + "=" * 50)
    print("Testing TTS (Piper)")
    print("=" * 50)

    from modules.tts import get_tts
    tts = get_tts()

    text = "Hello! I am your voice assistant."
    start = time.time()
    audio = tts.synthesize(text)
    elapsed = time.time() - start

    if audio:
        duration = len(audio) / (16000 * 2)
        print(f"Generated {len(audio)} bytes ({duration:.1f}s audio) in {elapsed:.2f}s")
        print(f"Real-time factor: {elapsed/duration:.2f}x")

        # Test chunked output
        chunks = list(tts.synthesize_chunks(text))
        print(f"Chunked into {len(chunks)} pieces")

        # Save to file for manual listening
        import wave
        test_path = "audio_cache/test_output.wav"
        with wave.open(test_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio)
        print(f"Saved test audio to {test_path}")
        print("✓ TTS module works")
    else:
        print("⚠ TTS produced no audio (model may not be installed)")
        print("  This is OK if you haven't downloaded Piper models yet")

    return True


def test_pipeline():
    """Test the full pipeline: STT → LLM → TTS."""
    print("\n" + "=" * 50)
    print("Testing Full Pipeline")
    print("=" * 50)

    from modules.stt import get_stt
    from modules.llm import get_llm
    from modules.tts import get_tts

    total_start = time.time()

    # Simulate: skip STT (use text directly), test LLM → TTS
    llm = get_llm()
    tts = get_tts()

    print("[1/2] LLM...")
    response = llm.chat("Tell me a fun fact about cats.")
    print(f"  → \"{response[:100]}...\"")

    print("[2/2] TTS...")
    audio = tts.synthesize(response)
    if audio:
        duration = len(audio) / (16000 * 2)
        print(f"  → {duration:.1f}s of audio")
    else:
        print("  → No audio (Piper not installed)")

    total = time.time() - total_start
    print(f"\nTotal pipeline time: {total:.2f}s")
    print("✓ Pipeline test complete")
    return True


if __name__ == "__main__":
    tests = {
        "stt": test_stt,
        "llm": test_llm,
        "tts": test_tts,
        "pipeline": test_pipeline,
    }

    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if test_name in tests:
            tests[test_name]()
        else:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(tests.keys())}")
    else:
        # Run all
        for name, fn in tests.items():
            try:
                fn()
            except Exception as e:
                print(f"\n✗ {name} failed: {e}")
