"""
Weather module — OpenWeatherMap current conditions.

Free tier API key: https://openweathermap.org/api  (sign up, use "Current Weather")
Set WEATHER_API_KEY and WEATHER_CITY in your .env file.

Results are cached for CACHE_TTL_SECONDS so every LLM request doesn't
hit the network.  If the API is unreachable the last good reading is
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
        if not config.WEATHER_API_KEY or not config.WEATHER_CITY:
            return None

        params = urllib.parse.urlencode({
            "q":     config.WEATHER_CITY,
            "appid": config.WEATHER_API_KEY,
            "units": config.WEATHER_UNITS,
        })
        url = f"https://api.openweathermap.org/data/2.5/weather?{params}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            print(f"[Weather] HTTP {e.code}: {e.reason} — check API key / city name")
        except Exception as e:
            print(f"[Weather] Fetch error: {e}")
        return None

    def get_summary(self) -> str | None:
        """
        Return a short natural-language weather summary for injection into the
        LLM system prompt, or None if weather is not configured / unavailable.

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
            desc     = d["weather"][0]["description"].capitalize()
            temp_c   = d["main"]["temp"]
            temp_f   = temp_c * 9 / 5 + 32
            humidity = d["main"]["humidity"]
            wind_ms  = d["wind"]["speed"]
            wind_kph = wind_ms * 3.6
            city     = d["name"]

            return (
                f"Current weather in {city}: {desc}, "
                f"{temp_c:.0f}°C ({temp_f:.0f}°F), "
                f"humidity {humidity}%, "
                f"wind {wind_kph:.0f} km/h."
            )
        except (KeyError, TypeError) as e:
            print(f"[Weather] Parse error: {e}")
            return None


# Singleton
_instance = None

def get_weather() -> WeatherClient:
    global _instance
    if _instance is None:
        _instance = WeatherClient()
    return _instance
