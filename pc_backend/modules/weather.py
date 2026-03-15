"""
Weather module — wttr.in (no API key required).

wttr.in is a free, open-source weather service. No signup needed.
Set WEATHER_CITY in your .env file (defaults to "London").

Results are cached for CACHE_TTL_SECONDS so every LLM request doesn't
hit the network.  If the service is unreachable the last good reading is
returned; if there is no reading yet, None is returned and the LLM
answers without weather context.
"""
import json
import time
import urllib.request
import urllib.parse
import urllib.error

import config

CACHE_TTL_SECONDS = 600  # 10 minutes


class WeatherClient:
    def __init__(self):
        self._cache: dict | None = None
        self._cache_time: float = 0

    def _fetch(self) -> dict | None:
        if not config.WEATHER_CITY:
            return None

        city = urllib.parse.quote(config.WEATHER_CITY)
        url = f"https://wttr.in/{city}?format=j1"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "esp32-voice-assistant/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            print(f"[Weather] HTTP {e.code}: {e.reason} — check city name")
        except Exception as e:
            print(f"[Weather] Fetch error: {e}")
        return None

    def get_summary(self) -> str | None:
        """
        Return a short natural-language weather summary for injection into the
        LLM system prompt, or None if weather is unavailable.

        Example: "Partly cloudy, 24°C (75°F), humidity 60%, wind 12 km/h."
        """
        now = time.monotonic()
        if self._cache is None or (now - self._cache_time) > CACHE_TTL_SECONDS:
            data = self._fetch()
            if data:
                self._cache = data
                self._cache_time = now
            elif self._cache is None:
                return None  # No cached data and fetch failed

        d = self._cache
        try:
            cur      = d["current_condition"][0]
            desc     = cur["weatherDesc"][0]["value"]
            temp_c   = cur["temp_C"]
            temp_f   = cur["temp_F"]
            humidity = cur["humidity"]
            wind_kph = cur["windspeedKmph"]
            city     = d["nearest_area"][0]["areaName"][0]["value"]

            return (
                f"Current weather in {city}: {desc}, "
                f"{temp_c}°C ({temp_f}°F), "
                f"humidity {humidity}%, "
                f"wind {wind_kph} km/h."
            )
        except (KeyError, IndexError, TypeError) as e:
            print(f"[Weather] Parse error: {e}")
            return None


# Singleton
_instance = None

def get_weather() -> WeatherClient:
    global _instance
    if _instance is None:
        _instance = WeatherClient()
    return _instance
