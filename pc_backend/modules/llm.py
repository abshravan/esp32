"""
LLM interaction module — primary: Google Gemini, fallback: Ollama (local).

When Gemini hits its quota limit the module automatically retries with
a local Ollama model if Ollama is running on the same machine.
Install Ollama → https://ollama.com  then run: ollama pull llama3.2
"""
import re
import time
import urllib.request
import json
from typing import List
import google.generativeai as genai
import config


def _rate_limit_message(err: Exception) -> str:
    """Return a user-friendly spoken message for a 429 rate-limit error."""
    match = re.search(r'retry in (\d+(?:\.\d+)?)s', str(err))
    if match:
        seconds = int(float(match.group(1))) + 1
        return f"I've hit the API rate limit. Please wait {seconds} seconds and try again."
    return "I've hit the API rate limit. Please wait a moment and try again."


def _is_rate_limit(err: Exception) -> bool:
    s = str(err)
    return '429' in s or 'quota' in s.lower() or 'ResourceExhausted' in type(err).__name__


def _ollama_chat(history: List[dict], user_text: str, model: str = "llama3.2") -> str:
    """
    Send a message to a local Ollama server (http://localhost:11434).
    Returns the reply text, or raises an exception if Ollama is not running.
    """
    messages = []
    if config.SYSTEM_PROMPT:
        messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
    for turn in history:
        role = "assistant" if turn["role"] == "model" else "user"
        messages.append({"role": role, "content": turn["parts"][0]})
    messages.append({"role": "user", "content": user_text})

    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"].strip()


class LLMChat:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY not set! Export it or add to .env file.\n"
                "Get your key at: https://aistudio.google.com/app/apikey"
            )

        genai.configure(api_key=config.GEMINI_API_KEY)

        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            system_instruction=config.SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                max_output_tokens=config.GEMINI_MAX_TOKENS,
                temperature=0.7,
            ),
        )

        # Conversation history: list of {"role": "user"/"model", "parts": ["text"]}
        self._history: List[dict] = []

        print(f"[LLM] Initialized with model: {config.GEMINI_MODEL}")

    def chat(self, user_text: str) -> str:
        """
        Send a message and get a response. Maintains conversation history.
        Returns the assistant's response text.
        """
        print(f"[LLM] User: \"{user_text}\"")
        start = time.time()

        # Build chat with history
        chat_session = self.model.start_chat(history=self._history)

        success = True
        try:
            response = chat_session.send_message(user_text)
            reply = response.text.strip()
        except Exception as e:
            if _is_rate_limit(e):
                print(f"[LLM] Gemini rate limit (429) — trying Ollama fallback...")
                try:
                    reply = _ollama_chat(self._history, user_text)
                    print(f"[LLM] Ollama fallback succeeded")
                except Exception as ollama_err:
                    print(f"[LLM] Ollama not available: {ollama_err}")
                    print("[LLM] Install Ollama → https://ollama.com  then: ollama pull llama3.2")
                    reply = _rate_limit_message(e)
                    success = False
            else:
                print(f"[LLM] Error: {e}")
                reply = "Sorry, I had trouble thinking about that. Could you try again?"
                success = False

        elapsed = time.time() - start
        print(f"[LLM] Response ({elapsed:.2f}s): \"{reply[:100]}{'...' if len(reply)>100 else ''}\"")

        # Only update history on success — don't pollute context with error fallbacks
        if success:
            self._history.append({"role": "user", "parts": [user_text]})
            self._history.append({"role": "model", "parts": [reply]})
            while len(self._history) > config.MAX_CONVERSATION_TURNS * 2:
                self._history.pop(0)
                self._history.pop(0)

        return reply

    async def chat_stream(self, user_text: str):
        """
        Send a message and stream the response token by token.
        Yields text chunks as they arrive.
        Also maintains conversation history.
        """
        print(f"[LLM] User (streaming): \"{user_text}\"")
        start = time.time()

        chat_session = self.model.start_chat(history=self._history)

        full_reply = ""
        stream_success = True
        try:
            response = chat_session.send_message(user_text, stream=True)
            for chunk in response:
                if chunk.text:
                    full_reply += chunk.text
                    yield chunk.text
        except Exception as e:
            stream_success = False
            if _is_rate_limit(e):
                print(f"[LLM] Rate limit (429): {e}")
                yield _rate_limit_message(e)
            else:
                print(f"[LLM] Stream error: {e}")
                yield "Sorry, something went wrong."

        elapsed = time.time() - start
        print(f"[LLM] Stream done ({elapsed:.2f}s): \"{full_reply[:100]}...\"")

        # Only update history on success — don't pollute context with error fallbacks
        if stream_success and full_reply:
            self._history.append({"role": "user", "parts": [user_text]})
            self._history.append({"role": "model", "parts": [full_reply]})
            while len(self._history) > config.MAX_CONVERSATION_TURNS * 2:
                self._history.pop(0)
                self._history.pop(0)

    def clear_history(self):
        """Reset conversation memory."""
        self._history.clear()
        print("[LLM] Conversation history cleared")

    def get_history_summary(self) -> str:
        """Return a brief summary of conversation history for debugging."""
        turns = len(self._history) // 2
        return f"{turns} turns in memory"


# Singleton
_instance = None

def get_llm() -> LLMChat:
    global _instance
    if _instance is None:
        _instance = LLMChat()
    return _instance
