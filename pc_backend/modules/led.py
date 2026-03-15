"""
LED command parsing for WS2812B voice control.

The LLM is instructed to append [LED:colorname] to its response when asked
to change the light.  This module extracts that tag, resolves it to RGB,
and strips it from the text before TTS synthesis.
"""
import re
from typing import Tuple

# (R, G, B) — tuned for WS2812B perception (GRB chip order handled by FastLED)
COLORS: dict[str, Tuple[int, int, int]] = {
    "red":        (255,   0,   0),
    "green":      (  0, 255,   0),
    "blue":       (  0,   0, 255),
    "white":      (255, 255, 255),
    "yellow":     (255, 200,   0),
    "orange":     (255, 100,   0),
    "purple":     (128,   0, 255),
    "pink":       (255,  20, 100),
    "cyan":       (  0, 255, 255),
    "warm":       (255, 150,  50),   # warm white
    "warm white": (255, 150,  50),
    "off":        (  0,   0,   0),
}

_TAG_RE = re.compile(r'\[LED:([^\]]+)\]', re.IGNORECASE)


def parse_led_command(text: str) -> Tuple[str, Tuple[int, int, int] | None]:
    """
    Scan *text* for a [LED:colorname] tag.

    Returns (clean_text, rgb) where:
      - clean_text has the tag stripped and whitespace tidied
      - rgb is (R, G, B) if a recognised color was found, else None

    Examples
    --------
    >>> parse_led_command("Sure! [LED:red]")
    ("Sure!", (255, 0, 0))
    >>> parse_led_command("Hello there.")
    ("Hello there.", None)
    """
    match = _TAG_RE.search(text)
    if not match:
        return text, None

    color_name = match.group(1).strip().lower()
    rgb = COLORS.get(color_name)

    if rgb is None:
        # Unknown color — strip the tag but don't send a command
        print(f"[LED] Unknown color name: '{color_name}'")

    clean = _TAG_RE.sub("", text).strip()
    # Collapse any double-spaces left behind
    clean = re.sub(r"  +", " ", clean)
    return clean, rgb
