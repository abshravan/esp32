"""
LLM interaction module — Ollama (local).

Install Ollama → https://ollama.com  then run: ollama pull llama3.2
"""
import time
import json
import urllib.request
from typing import List
import config


class LLMChat:
    def __init__(self):
        self._history: List[dict] = []

        # Verify Ollama is reachable at startup
        try:
            req = urllib.request.Request(f"{config.OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            print(f"[LLM] Warning: Ollama not reachable at {config.OLLAMA_URL}: {e}")
            print(f"[LLM] Install Ollama → https://ollama.com  then: ollama pull {config.OLLAMA_MODEL}")

        print(f"[LLM] Initialized with model: {config.OLLAMA_MODEL} via {config.OLLAMA_URL}")

    def _build_messages(self, user_text: str) -> List[dict]:
        messages = []
        if config.SYSTEM_PROMPT:
            messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
        messages.extend(self._history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def chat(self, user_text: str) -> str:
        """Send a message and get a response. Maintains conversation history."""
        print(f"[LLM] User: \"{user_text}\"")
        start = time.time()

        payload = json.dumps({
            "model": config.OLLAMA_MODEL,
            "messages": self._build_messages(user_text),
            "stream": False,
            "options": {
                # Hard token cap — prevents long TTS responses that overflow
                # the ESP32 playback buffer or take too long to speak aloud.
                "num_predict": config.MAX_RESPONSE_TOKENS,
            },
        }).encode()

        req = urllib.request.Request(
            f"{config.OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        reply = None
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                reply = data["message"]["content"].strip()
                break
            except Exception as e:
                print(f"[LLM] Error (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    time.sleep(1)
        if reply is None:
            return "Sorry, I had trouble thinking about that. Could you try again?"

        elapsed = time.time() - start
        print(f"[LLM] Response ({elapsed:.2f}s): \"{reply[:100]}{'...' if len(reply)>100 else ''}\"")

        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": reply})
        while len(self._history) > config.MAX_CONVERSATION_TURNS * 2:
            self._history.pop(0)
            self._history.pop(0)

        return reply

    def clear_history(self):
        """Reset conversation memory."""
        self._history.clear()
        print("[LLM] Conversation history cleared")

    def get_history_summary(self) -> str:
        turns = len(self._history) // 2
        return f"{turns} turns in memory"


# Singleton
_instance = None

def get_llm() -> LLMChat:
    global _instance
    if _instance is None:
        _instance = LLMChat()
    return _instance
