"""t6: inline preview, the ASCII fallback, and never faking a preview."""

from __future__ import annotations

import struct
import zlib

from innereye import preview


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A real 8-bit truecolor PNG, built with the stdlib."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_ghostty_is_detected() -> None:
    assert preview.supports_kitty_graphics({"TERM_PROGRAM": "ghostty"})
    assert preview.supports_kitty_graphics({"TERM": "xterm-kitty"})
    assert not preview.supports_kitty_graphics({"TERM": "dumb"})


def test_kitty_sequence_is_chunked_and_well_formed() -> None:
    seq = preview.kitty_sequence(_png(4, 4, (255, 0, 0)))
    assert seq.startswith("\033_Ga=T,f=100,")
    assert seq.endswith("\033\\\n")


def test_png_decodes_without_a_dependency() -> None:
    decoded = preview.decode_png(_png(6, 4, (10, 200, 30)))
    assert decoded is not None
    width, height, pixels = decoded
    assert (width, height) == (6, 4)
    assert len(pixels) == 24
    assert pixels[0] == (10, 200, 30)


def test_non_png_bytes_decode_to_none() -> None:
    assert preview.decode_png(b"RIFF....WEBP") is None


def test_inline_path_in_a_capable_terminal() -> None:
    text, result = preview.preview(_png(8, 8, (0, 0, 0)), "a.png", env={"TERM_PROGRAM": "ghostty"})
    assert result.method == "kitty"
    assert text.startswith("\033_G")


def test_ascii_fallback_in_a_terminal_without_graphics() -> None:
    text, result = preview.preview(_png(16, 8, (255, 255, 255)), "a.png", env={"TERM": "dumb"})
    assert result.method == "ascii"
    assert text.strip()
    assert "@" in text  # white maps to the dense end of the ramp
    assert "no inline graphics" in result.describe()


def test_undecodable_media_is_described_never_faked(tmp_path) -> None:
    """The rule: never print only a path and call it a preview."""
    text, result = preview.preview(b"RIFFxxxxWEBPVP8 ", "clip.webp", env={"TERM": "dumb"})
    assert result.method == "described"
    assert text == ""
    assert "cannot render" in result.describe()
    assert "clip.webp" in result.describe()


def test_ascii_art_respects_requested_width() -> None:
    _, _, pixels = preview.decode_png(_png(20, 10, (128, 128, 128)))
    art = preview.ascii_art(20, 10, pixels, cols=10)
    assert all(len(line) == 10 for line in art.splitlines())
