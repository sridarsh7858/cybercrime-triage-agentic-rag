"""Generate the synthetic scam screenshot used by the preview recording.

    python scripts/make_sample_screenshot.py

Writes assets/sample-scam-screenshot.png — a mock phone screenshot of a
phishing SMS, deliberately padded with the status-bar noise that Node A of the
pipeline exists to strip: a carrier name, a clock, and a battery percentage.
Feeding it through the app demonstrates both OCR and the sanitiser, since none
of that chrome should reach the triage output.

The bank is fictitious on purpose. A demo asset should not be a ready-made
phishing message attributed to a real institution, and the pipeline behaves
identically either way.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "sample-scam-screenshot.png")

W, H = 440, 800
BG = (12, 15, 22)
BAR = (22, 26, 36)
BUBBLE = (32, 37, 50)
TEXT = (232, 236, 245)
MUTED = (140, 149, 168)
LINK = (110, 175, 255)

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType face, falling back to PIL's bitmap default."""
    for candidate in (
        os.path.join(_FONT_DIR, name),
        f"/usr/share/fonts/truetype/dejavu/{name}",
        name,
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    words, lines, line = text.split(), [], ""
    for word in words:
        probe = f"{line} {word}".strip()
        if draw.textlength(probe, font=font) <= max_width:
            line = probe
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _bubble(draw, top, text, font, *, link_lines=()):
    """Draw one message bubble; returns the y coordinate below it."""
    pad, margin = 14, 18
    max_text = W - 2 * margin - 2 * pad - 40
    lines = _wrap(draw, text, font, max_text)
    line_h = font.size + 7
    height = len(lines) * line_h + 2 * pad

    draw.rounded_rectangle(
        [margin, top, W - margin - 40, top + height], radius=14, fill=BUBBLE
    )
    y = top + pad
    for line in lines:
        colour = LINK if any(marker in line for marker in link_lines) else TEXT
        draw.text((margin + pad, y), line, font=font, fill=colour)
        y += line_h
    return top + height


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    f_small = _font("segoeui.ttf", 15)
    f_body = _font("segoeui.ttf", 17)
    f_bold = _font("segoeuib.ttf", 18)

    # --- Status bar: the UI noise the sanitiser must discard ----------------
    draw.rectangle([0, 0, W, 34], fill=BAR)
    draw.text((16, 9), "Sprint", font=f_small, fill=MUTED)
    draw.text((W // 2 - 26, 9), "9:41 AM", font=f_small, fill=MUTED)
    draw.text((W - 78, 9), "78%", font=f_small, fill=MUTED)
    draw.rounded_rectangle([W - 44, 12, W - 18, 25], radius=3, outline=MUTED)
    draw.rectangle([W - 42, 14, W - 30, 23], fill=MUTED)

    # --- Conversation header ------------------------------------------------
    draw.rectangle([0, 34, W, 84], fill=BAR)
    draw.text((18, 44), "VM-MERIBK", font=f_bold, fill=TEXT)
    draw.text((18, 64), "SMS  ·  Today", font=f_small, fill=MUTED)

    # --- Messages -----------------------------------------------------------
    y = 104
    y = _bubble(
        draw,
        y,
        "Dear Customer, your Meridian Bank KYC has EXPIRED. Your account will "
        "be BLOCKED today.",
        f_body,
    )
    y = _bubble(
        draw,
        y + 12,
        "Update now: http://meridian-kyc-verify.in/update",
        f_body,
        link_lines=("http",),
    )
    y = _bubble(
        draw,
        y + 12,
        "Our executive will call you shortly. Share the OTP sent to your "
        "registered mobile to complete the verification.",
        f_body,
    )
    y = _bubble(
        draw,
        y + 12,
        "Helpline: +91 98XXXX4421",
        f_body,
    )

    draw.text((22, y + 26), "Delivered 11:02 AM", font=f_small, fill=MUTED)

    # --- Bottom nav chrome (more noise) ------------------------------------
    draw.rectangle([0, H - 56, W, H], fill=BAR)
    draw.rounded_rectangle([18, H - 44, W - 90, H - 14], radius=15, outline=MUTED)
    draw.text((32, H - 38), "Text message", font=f_small, fill=MUTED)
    draw.text((W - 70, H - 38), "Send", font=f_small, fill=LINK)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print(f"[sample] wrote {OUT} ({os.path.getsize(OUT) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
