"""Terminals cannot show images — so decide deliberately how a preview reaches a human.

Three paths, in descending fidelity:

1. **Inline graphics** where the terminal implements the kitty graphics
   protocol (ghostty and kitty both do). PNG bytes go straight down the wire.
2. **ASCII art** where it does not. This needs a decoded image, and the runtime
   package has no dependencies — so :func:`decode_png` is a small stdlib PNG
   reader built on ``zlib``. It handles the 8-bit truecolor and grayscale forms
   ComfyUI's ``SaveImage`` actually emits.
3. **A described fallback** when the bytes cannot be decoded at all — animated
   WebP, for instance, which has no stdlib decoder.

The rule that shapes all three: **preview never prints only a path and calls it
a preview.** When innereye cannot show you the picture it says so, and says
which path it took, rather than printing a filename and letting you assume.
"""

from __future__ import annotations

import base64
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

# Kitty graphics: direct transmission, PNG payload, chunked base64.
_KITTY_CHUNK = 4096
_ASCII_RAMP = " .:-=+*#%@"

_KITTY_TERMS = ("xterm-kitty", "xterm-ghostty")
_KITTY_PROGRAMS = ("ghostty", "kitty", "wezterm")


@dataclass(frozen=True)
class PreviewResult:
    """What was rendered, and how — so the caller can report it honestly."""

    method: str  # "kitty" | "ascii" | "described"
    detail: str

    def describe(self) -> str:
        return self.detail


def supports_kitty_graphics(env: dict[str, str] | None = None) -> bool:
    """True when the terminal implements the kitty graphics protocol."""
    environ = env if env is not None else dict(os.environ)
    if environ.get("TERM", "") in _KITTY_TERMS:
        return True
    return environ.get("TERM_PROGRAM", "").lower() in _KITTY_PROGRAMS


def kitty_sequence(png: bytes) -> str:
    """The escape sequence that draws ``png`` inline, chunked per the protocol."""
    payload = base64.b64encode(png).decode("ascii")
    if not payload:
        return ""
    chunks = [payload[i : i + _KITTY_CHUNK] for i in range(0, len(payload), _KITTY_CHUNK)]
    out: list[str] = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        if index == 0:
            out.append(f"\033_Ga=T,f=100,m={more};{chunk}\033\\")
        else:
            out.append(f"\033_Gm={more};{chunk}\033\\")
    return "".join(out) + "\n"


def decode_png(data: bytes) -> tuple[int, int, list[tuple[int, int, int]]] | None:
    """Minimal stdlib PNG decoder. Returns ``(width, height, rgb)`` or ``None``.

    Deliberately narrow: 8-bit grayscale, truecolor and truecolor+alpha, no
    interlacing. That covers what ComfyUI writes. Anything else returns
    ``None`` and the caller falls back to a described preview rather than
    guessing at the pixels.
    """
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None

    pos = 8
    width = height = depth = color_type = interlace = 0
    idat = bytearray()

    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # header + body + crc

        if kind == b"IHDR" and len(body) >= 13:
            width, height, depth, color_type = struct.unpack(">IIBB", body[:10])
            interlace = body[12]
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break

    if not (width and height) or depth != 8 or interlace != 0:
        return None
    channels = {0: 1, 2: 3, 6: 4}.get(color_type)
    if channels is None:
        return None

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None

    stride = width * channels
    if len(raw) < (stride + 1) * height:
        return None

    pixels: list[tuple[int, int, int]] = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        _unfilter(filter_type, line, previous, channels)
        for x in range(0, stride, channels):
            if channels == 1:
                value = line[x]
                pixels.append((value, value, value))
            else:
                pixels.append((line[x], line[x + 1], line[x + 2]))
        previous = line

    return width, height, pixels


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, channels: int) -> None:
    """Reverse one PNG scanline filter in place (spec section 9.2)."""
    if filter_type == 0:
        return
    for i in range(len(line)):
        left = line[i - channels] if i >= channels else 0
        up = previous[i]
        up_left = previous[i - channels] if i >= channels else 0
        if filter_type == 1:
            line[i] = (line[i] + left) & 0xFF
        elif filter_type == 2:
            line[i] = (line[i] + up) & 0xFF
        elif filter_type == 3:
            line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:
            line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def ascii_art(width: int, height: int, pixels: list[tuple[int, int, int]], cols: int = 60) -> str:
    """Render decoded pixels as text, correcting for cell aspect ratio."""
    cols = max(8, min(cols, width))
    rows = max(4, int(height / width * cols * 0.5))
    lines: list[str] = []
    for row in range(rows):
        chars: list[str] = []
        for col in range(cols):
            x = min(width - 1, col * width // cols)
            y = min(height - 1, row * height // rows)
            r, g, b = pixels[y * width + x]
            luma = (r * 299 + g * 587 + b * 114) // 1000
            chars.append(_ASCII_RAMP[luma * (len(_ASCII_RAMP) - 1) // 255])
        lines.append("".join(chars))
    return "\n".join(lines)


def preview(
    data: bytes,
    filename: str,
    *,
    env: dict[str, str] | None = None,
    cols: int = 60,
) -> tuple[str, PreviewResult]:
    """Return ``(renderable_text, result)`` for showing ``data`` in a terminal.

    The caller writes the text to stdout and reports ``result.describe()`` as a
    diagnostic, so it is always visible which of the three paths was taken.
    """
    suffix = Path(filename).suffix.lower()
    size_kb = max(1, len(data) // 1024)

    if suffix == ".png" and supports_kitty_graphics(env):
        return kitty_sequence(data), PreviewResult("kitty", f"inline image ({size_kb} KiB)")

    if suffix == ".png":
        decoded = decode_png(data)
        if decoded is not None:
            width, height, pixels = decoded
            art = ascii_art(width, height, pixels, cols=cols)
            return art + "\n", PreviewResult(
                "ascii",
                f"ASCII rendering ({width}x{height}); this terminal has no inline graphics",
            )

    return "", PreviewResult(
        "described",
        (
            f"cannot render {suffix or 'this file'} in a terminal "
            f"({size_kb} KiB) -- open {filename} to view it"
        ),
    )
