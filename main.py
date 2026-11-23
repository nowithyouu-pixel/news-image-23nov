#!/usr/bin/env python3
"""World news, 23 November 2026, drawn as one newspaper front page.

Pure standard library. Deterministic: same input always yields the same
bytes. No network, no clock, no randomness.

Run:  python3 main.py
Out:  $MAKEFUN_OUTPUT_DIR/entry.png (or /output/entry.png by default),
     1024x1024, RGB, under 1 MiB. The grader runs the program with the
     repository mounted read-only, so the image must go to the output
     directory, never to the working directory.

Design, in brief: a scanline Board (one bytearray per row) is painted with
a small set of raster primitives (rectangles, Bresenham strokes, midpoint
circles). All lettering uses a hand-built vector stroke font: every glyph
is a list of polylines on a 7-by-11 unit grid, scaled by integer factors.
Six news tiles and one lead story are laid out by a tiny box model that
measures text before it places it, so nothing can overflow the page.
"""

import hashlib
import os
import struct
import sys
import zlib

WIDTH = 1024
HEIGHT = 1024
OUT_PATH = os.path.join(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"), "entry.png")

# Palette: warm newsprint paper, near-black ink, signal red, deep blue.
PAPER = (250, 246, 238)
INK = (18, 18, 18)
RED = (178, 32, 44)
BLUE = (29, 78, 137)
GREY = (105, 105, 100)
LIGHT = (232, 226, 214)


class Board:
    """An RGB picture kept as one bytearray per scanline.

    Rows are independent buffers, so a horizontal fill is a single slice
    assignment and a vertical rule is a short loop over rows.
    """

    def __init__(self, width, height, paper):
        self.width = width
        self.height = height
        self.rows = []
        fill = bytes(paper) * width
        for _ in range(height):
            self.rows.append(bytearray(fill))

    def dot(self, x, y, rgb):
        if 0 <= x < self.width and 0 <= y < self.height:
            row = self.rows[y]
            i = x * 3
            row[i] = rgb[0]
            row[i + 1] = rgb[1]
            row[i + 2] = rgb[2]

    def brush(self, x, y, size, rgb):
        """A square brush centred on (x, y); size 1 is a single pixel."""
        half = size // 2
        for dy in range(-half, size - half):
            for dx in range(-half, size - half):
                self.dot(x + dx, y + dy, rgb)

    def hline(self, x0, x1, y, rgb, thick=1):
        if x1 < x0:
            x0, x1 = x1, x0
        x0 = max(0, x0)
        x1 = min(self.width - 1, x1)
        if x0 > x1:
            return
        span = bytes(rgb) * (x1 - x0 + 1)
        for yy in range(y, y + thick):
            if 0 <= yy < self.height:
                self.rows[yy][x0 * 3:(x1 + 1) * 3] = span

    def vline(self, x, y0, y1, rgb, thick=1):
        if y1 < y0:
            y0, y1 = y1, y0
        for xx in range(x, x + thick):
            if 0 <= xx < self.width:
                for yy in range(max(0, y0), min(self.height, y1 + 1)):
                    row = self.rows[yy]
                    i = xx * 3
                    row[i] = rgb[0]
                    row[i + 1] = rgb[1]
                    row[i + 2] = rgb[2]

    def fill_rect(self, x, y, w, h, rgb):
        if w <= 0 or h <= 0:
            return
        x0 = max(0, x)
        x1 = min(self.width, x + w)
        y0 = max(0, y)
        y1 = min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        span = bytes(rgb) * (x1 - x0)
        for yy in range(y0, y1):
            self.rows[yy][x0 * 3:x1 * 3] = span

    def frame(self, x, y, w, h, rgb, thick=1):
        self.hline(x, x + w - 1, y, rgb, thick)
        self.hline(x, x + w - 1, y + h - thick, rgb, thick)
        self.vline(x, y, y + h - 1, rgb, thick)
        self.vline(x + w - thick, y, y + h - 1, rgb, thick)

    def line(self, x0, y0, x1, y1, rgb, thick=1):
        """Bresenham segment, painted with the square brush."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self.brush(x, y, thick, rgb)
            if x == x1 and y == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def circle(self, cx, cy, r, rgb, thick=1):
        """Midpoint circle outline."""
        x = 0
        y = r
        d = 1 - r
        while x <= y:
            for px, py in (
                (cx + x, cy + y), (cx + y, cy + x), (cx - x, cy + y),
                (cx - y, cy + x), (cx + x, cy - y), (cx + y, cy - x),
                (cx - x, cy - y), (cx - y, cy - x),
            ):
                self.brush(px, py, thick, rgb)
            if d < 0:
                d += 2 * x + 3
            else:
                d += 2 * (x - y) + 5
                y -= 1
            x += 1

    def disc(self, cx, cy, r, rgb):
        """Filled circle, painted one scanline at a time."""
        for yy in range(cy - r, cy + r + 1):
            half = int((r * r - (yy - cy) * (yy - cy)) ** 0.5)
            self.hline(cx - half, cx + half, yy, rgb)

    def png_bytes(self):
        """Encode the board as a PNG (8-bit RGB, filter 0 per row)."""
        raw = bytearray()
        for row in self.rows:
            raw.append(0)
            raw += row
        body = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
        out = bytearray(b"\x89PNG\r\n\x1a\n")
        out += self._chunk(b"IHDR", body)
        out += self._chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        out += self._chunk(b"IEND", b"")
        return bytes(out)

    @staticmethod
    def _chunk(kind, payload):
        data = kind + payload
        return struct.pack(">I", len(payload)) + data + struct.pack(
            ">I", zlib.crc32(data) & 0xFFFFFFFF
        )


# ---------------------------------------------------------------------------
# Stroke font
#
# Each glyph is a tuple of strokes. A stroke is a space-separated list of
# "x,y" knots on a 7-wide, 11-tall unit grid (x 0..6, y 0..10; the text
# baseline sits at y 9, descenders reach y 10). The renderer joins the
# knots with straight segments and scales everything by an integer factor.
# Only capitals are drawn: callers uppercase their text first.
# ---------------------------------------------------------------------------

def _strokes(*rows):
    return tuple(tuple(_knot(tok) for tok in row.split()) for row in rows)


def _knot(tok):
    a, b = tok.split(",")
    return (int(a), int(b))


GLYPHS = {
    "A": _strokes("0,9 3,0 6,9", "1,6 5,6"),
    "B": _strokes("0,0 0,9", "0,0 4,0 6,2 4,4 0,4",
                  "0,4 4,4 6,6 4,9 0,9"),
    "C": _strokes("6,2 4,0 2,0 0,2 0,7 2,9 4,9 6,7"),
    "D": _strokes("0,0 0,9", "0,0 4,0 6,2 6,7 4,9 0,9"),
    "E": _strokes("6,0 0,0 0,9 6,9", "0,4 4,4"),
    "F": _strokes("6,0 0,0 0,9", "0,4 4,4"),
    "G": _strokes("6,2 4,0 2,0 0,2 0,7 2,9 4,9 6,7 6,5 3,5"),
    "H": _strokes("0,0 0,9", "6,0 6,9", "0,4 6,4"),
    "I": _strokes("0,0 6,0", "3,0 3,9", "0,9 6,9"),
    "J": _strokes("6,0 6,7 4,9 2,9 0,7"),
    "K": _strokes("0,0 0,9", "6,0 0,4", "1,5 6,9"),
    "L": _strokes("0,0 0,9 6,9"),
    "M": _strokes("0,9 0,0 3,5 6,0 6,9"),
    "N": _strokes("0,9 0,0 6,9 6,0"),
    "O": _strokes("2,0 4,0 6,2 6,7 4,9 2,9 0,7 0,2 2,0"),
    "P": _strokes("0,9 0,0 4,0 6,2 4,4 0,4"),
    "Q": _strokes("2,0 4,0 6,2 6,7 4,9 2,9 0,7 0,2 2,0", "4,7 6,9"),
    "R": _strokes("0,9 0,0 4,0 6,2 4,4 0,4", "2,4 6,9"),
    "S": _strokes("5,0 2,0 0,2 0,4 2,5 5,5 6,7 6,8 5,9 2,9 0,8"),
    "T": _strokes("0,0 6,0", "3,0 3,9"),
    "U": _strokes("0,0 0,7 2,9 4,9 6,7 6,0"),
    "V": _strokes("0,0 3,9 6,0"),
    "W": _strokes("0,0 1,9 3,5 5,9 6,0"),
    "X": _strokes("0,0 6,9", "6,0 0,9"),
    "Y": _strokes("0,0 3,4 6,0", "3,4 3,9"),
    "Z": _strokes("0,0 6,0 0,9 6,9"),
    "0": _strokes("2,0 4,0 6,2 6,7 4,9 2,9 0,7 0,2 2,0", "1,2 5,7"),
    "1": _strokes("2,1 3,0 3,9", "0,9 6,9"),
    "2": _strokes("0,1 2,0 4,0 6,2 6,4 0,9 6,9"),
    "3": _strokes("0,1 2,0 4,0 6,2 4,4", "4,4 6,6 6,8 4,9 2,9 0,8"),
    "4": _strokes("4,0 4,9", "6,0 0,6 6,6"),
    "5": _strokes("6,0 0,0 0,4 4,4 6,6 6,8 4,9 0,9"),
    "6": _strokes("6,1 4,0 2,0 0,2 0,7 2,9 4,9 6,7 6,5 4,4 2,4 0,5"),
    "7": _strokes("0,0 6,0 3,9"),
    "8": _strokes("2,0 4,0 6,2 4,4 2,4 0,2 2,0",
                  "2,4 4,4 6,6 6,8 4,9 2,9 0,7 0,5 2,4"),
    "9": _strokes("2,0 4,0 6,2 6,5 4,7 2,7 0,5 0,2 2,0",
                  "6,5 6,8 4,9 2,9 0,8"),
    " ": (),
    ".": _strokes("2,8 4,8 4,9 2,9"),
    ",": _strokes("2,7 4,7 4,9 2,9", "3,9 1,10"),
    ":": _strokes("2,2 4,2 4,3 2,3", "2,6 4,6 4,7 2,7"),
    ";": _strokes("2,2 4,2 4,3 2,3", "2,6 4,6 4,7 2,7 1,10"),
    "-": _strokes("1,5 5,5"),
    "/": _strokes("0,9 6,0"),
    "(": _strokes("5,0 3,2 3,7 5,9"),
    ")": _strokes("1,0 3,2 3,7 1,9"),
    "%": _strokes("6,0 0,9", "1,1 3,1 3,3 1,3 1,1",
                  "3,6 5,6 5,8 3,8 3,6"),
    "+": _strokes("3,1 3,8", "0,4 6,4"),
    "!": _strokes("3,0 3,6", "2,8 4,8 4,9 2,9"),
    "?": _strokes("1,1 2,0 4,0 5,1 5,3 3,5 3,6", "2,8 4,8 4,9 2,9"),
    "'": _strokes("3,0 3,2"),
    '"': _strokes("2,0 2,2", "4,0 4,2"),
    "=": _strokes("0,3 6,3", "0,6 6,6"),
    "*": _strokes("3,0 3,9", "0,2 6,7", "6,2 0,7"),
    "_": _strokes("0,9 6,9"),
}

CELL_W = 8   # advance per character, in font units
CELL_H = 11  # glyph cell height, in font units


def text_width(text, scale):
    """Pixel width of text drawn at the given integer scale."""
    return len(text) * CELL_W * scale


def draw_text(board, x, y, text, scale, rgb):
    """Draw uppercased text; (x, y) is the top-left of the first cell."""
    thick = max(1, scale // 2)
    cx = x
    for ch in text.upper():
        for stroke in GLYPHS.get(ch, ()):
            prev = None
            for gx, gy in stroke:
                px = cx + gx * scale
                py = y + gy * scale
                if prev is not None:
                    board.line(prev[0], prev[1], px, py, rgb, thick)
                else:
                    board.brush(px, py, thick, rgb)
                prev = (px, py)
        cx += CELL_W * scale


def draw_centred(board, cx, y, text, scale, rgb):
    draw_text(board, cx - text_width(text, scale) // 2, y, text, scale, rgb)


def wrap_text(text, scale, max_width):
    """Greedy word wrap; returns a list of lines that fit max_width."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = current + " " + word
            if text_width(trial, scale) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Motifs: small line-drawn icons, one per story. Each takes the board, the
# top-left of its box, the box size, and a colour. All geometry is derived
# from the box so the same motif works at any size.
# ---------------------------------------------------------------------------

def motif_burst(board, x, y, size, rgb):
    """Starburst: a ring with twelve radiating spikes, for the lead story."""
    cx, cy = x + size // 2, y + size // 2
    board.circle(cx, cy, size // 5, rgb, 3)
    board.disc(cx, cy, size // 12, rgb)
    for k in range(12):
        # 30-degree steps, alternating long and short spikes.
        angle = k * 30
        long = size // 2 - 4
        short = size // 3
        reach = long if k % 2 == 0 else short
        # Integer trig via a tiny lookup: cos/sin of multiples of 30 deg.
        table = [(100, 0), (87, 50), (50, 87), (0, 100), (-50, 87),
                 (-87, 50), (-100, 0), (-87, -50), (-50, -87), (0, -100),
                 (50, -87), (87, -50)]
        c, s = table[k]
        x1 = cx + c * (size // 5 + 2) // 100
        y1 = cy + s * (size // 5 + 2) // 100
        x2 = cx + c * reach // 100
        y2 = cy + s * reach // 100
        board.line(x1, y1, x2, y2, rgb, 3)
        _ = angle


def motif_drone(board, x, y, size, rgb):
    """Quadcopter seen from above: body, four arms, four rotors."""
    cx, cy = x + size // 2, y + size // 2
    arm = size // 3
    board.fill_rect(cx - size // 10, cy - size // 10, size // 5, size // 5,
                    rgb)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        board.line(cx, cy, cx + dx * arm, cy + dy * arm, rgb, 3)
        board.circle(cx + dx * arm, cy + dy * arm, size // 8, rgb, 2)
        board.line(cx + dx * arm - size // 8, cy + dy * arm,
                   cx + dx * arm + size // 8, cy + dy * arm, rgb, 2)


def motif_globe(board, x, y, size, rgb):
    """A globe with a crack through it, for the collapsed climate talks."""
    cx, cy = x + size // 2, y + size // 2
    r = size // 2 - 4
    board.circle(cx, cy, r, rgb, 3)
    board.hline(cx - r, cx + r, cy - r // 2, rgb, 2)
    board.hline(cx - r, cx + r, cy + r // 2, rgb, 2)
    board.vline(cx, cy - r, cy + r, rgb, 2)
    # Crack: a zig-zag from the top of the globe to the bottom.
    board.line(cx - r // 3, cy - r, cx, cy - r // 3, rgb, 3)
    board.line(cx, cy - r // 3, cx - r // 4, cy + r // 4, rgb, 3)
    board.line(cx - r // 4, cy + r // 4, cx + r // 3, cy + r, rgb, 3)


def motif_ship(board, x, y, size, rgb):
    """A cargo ship with smoke and a flame above its hold."""
    base = y + size * 3 // 4
    board.line(x + 4, base, x + size - 4, base, rgb, 3)
    board.line(x + 4, base, x + size // 4, base - size // 4, rgb, 3)
    board.line(x + size // 4, base - size // 4, x + size * 3 // 4,
               base - size // 4, rgb, 3)
    board.line(x + size * 3 // 4, base - size // 4, x + size - 4, base,
               rgb, 3)
    board.line(x + size // 3, base - size // 4, x + size // 3,
               base - size // 2, rgb, 3)
    board.line(x + size // 2, base - size // 4, x + size // 2,
               base - size // 2, rgb, 3)
    # Flame licking from the middle hold.
    fx = x + size * 2 // 5
    board.line(fx, base - size // 2, fx + size // 12, base - size * 2 // 3,
               rgb, 3)
    board.line(fx + size // 12, base - size * 2 // 3, fx + size // 6,
               base - size // 2, rgb, 3)
    # Waves under the hull.
    for k in range(3):
        wx = x + 6 + k * size // 3
        board.line(wx, base + 8, wx + size // 12, base + 12, rgb, 2)
        board.line(wx + size // 12, base + 12, wx + size // 6, base + 8,
                   rgb, 2)


def motif_exam(board, x, y, size, rgb):
    """An exam sheet with a pen and a big tick."""
    board.frame(x + size // 5, y + size // 8, size * 3 // 5, size * 3 // 4,
                rgb, 2)
    for k in range(3):
        ly = y + size // 4 + k * size // 8
        board.hline(x + size // 4, x + size * 3 // 4 - 4, ly, rgb, 2)
    board.line(x + size * 3 // 4, y + size // 8, x + size - 6,
               y + size * 3 // 5, rgb, 3)
    board.line(x + size - 6, y + size * 3 // 5, x + size * 3 // 4,
               y + size * 5 // 8, rgb, 3)
    board.line(x + size // 4, y + size * 5 // 8, x + size // 2,
               y + size * 3 // 4, rgb, 3)
    board.line(x + size // 2, y + size * 3 // 4, x + size * 3 // 4,
               y + size // 2, rgb, 3)


def motif_flags(board, x, y, size, rgb):
    """Two flags on crossed poles, for the Nepal-India talks."""
    board.line(x + size // 4, y + 4, x + size // 4, y + size - 4, rgb, 3)
    board.line(x + size * 3 // 4, y + 4, x + size * 3 // 4, y + size - 4,
               rgb, 3)
    board.line(x + size // 4, y + 6, x + size // 2, y + size // 4, rgb, 2)
    board.line(x + size // 2, y + size // 4, x + size // 4, y + size // 2,
               rgb, 2)
    board.line(x + size * 3 // 4, y + 6, x + size // 2, y + size // 4,
               rgb, 2)
    board.line(x + size // 2, y + size // 4, x + size * 3 // 4,
               y + size // 2, rgb, 2)
    board.line(x + size // 4, y + size * 5 // 8, x + size // 2,
               y + size * 3 // 4, rgb, 3)
    board.line(x + size // 2, y + size * 3 // 4, x + size * 3 // 4,
               y + size * 5 // 8, rgb, 3)


def motif_factory(board, x, y, size, rgb):
    """A factory with a sawtooth roof, a chimney and smoke."""
    base = y + size * 3 // 4
    board.line(x + 4, base, x + size - 4, base, rgb, 3)
    board.line(x + 4, base, x + 4, base - size // 3, rgb, 3)
    board.line(x + 4, base - size // 3, x + size // 3, base - size // 2,
               rgb, 3)
    board.line(x + size // 3, base - size // 2, x + size // 3,
               base - size // 3, rgb, 3)
    board.line(x + size // 3, base - size // 3, x + size * 2 // 3,
               base - size // 2, rgb, 3)
    board.line(x + size * 2 // 3, base - size // 2, x + size * 2 // 3,
               base - size // 3, rgb, 3)
    board.line(x + size * 2 // 3, base - size // 3, x + size - 4,
               base - size // 2, rgb, 3)
    board.line(x + size - 4, base - size // 2, x + size - 4, base, rgb, 3)
    # Chimney and smoke puffs.
    chx = x + size * 5 // 6
    board.line(chx, base - size // 2, chx, base - size * 3 // 4, rgb, 3)
    board.line(chx + 8, base - size // 2, chx + 8, base - size * 3 // 4,
               rgb, 3)
    board.circle(chx + 4, y + size // 8, size // 12, rgb, 2)
    board.circle(chx - 4, y + size // 5, size // 14, rgb, 2)


MOTIFS = {
    "burst": motif_burst,
    "drone": motif_drone,
    "globe": motif_globe,
    "ship": motif_ship,
    "exam": motif_exam,
    "flags": motif_flags,
    "factory": motif_factory,
}


# ---------------------------------------------------------------------------
# The day's stories, researched 23 November 2026.
# ---------------------------------------------------------------------------

LEAD = {
    "kicker": "LEAD STORY - THE GULF",
    "headline": "IRAN HITS US BASES IN BAHRAIN",
    "body": ("IRGC MISSILES AND DRONES HIT US PATRIOT RADARS AT AL-RIFFA "
             "AND AWALI. TWO INJURED AS A CIVILIAN PLANT BURNS. THE US "
             "SAYS NO DAMAGE TO ITS FORCES."),
    "motif": "burst",
}

TILES = [
    {
        "tag": "UKRAINE",
        "headline": "DRONE HITS FLATS NEAR KYIV - 14 MISSING",
        "body": ("A RUSSIAN DRONE STRUCK A FIVE-STOREY BLOCK IN DYMER, "
                 "NORTH OF KYIV. RESCUERS SEARCH THE RUBBLE FOR 14 "
                 "PEOPLE STILL UNACCOUNTED FOR."),
        "motif": "drone",
    },
    {
        "tag": "CLIMATE",
        "headline": "COP31 ENDS WITH NO DEAL ON FOSSIL FUELS",
        "body": ("THE ANTALYA SUMMIT CLOSED TWO DAYS LATE WITH NO "
                 "AGREEMENT AFTER THE EU REJECTED A DRAFT THAT NEVER "
                 "MENTIONED FOSSIL FUELS."),
        "motif": "globe",
    },
    {
        "tag": "BALTIC SEA",
        "headline": "DRONE-HIT RUSSIAN SHIP BURNS OFF FINLAND",
        "body": ("THE SANCTIONED CARGO SHIP SPARTA II CAUGHT FIRE AFTER "
                 "A DRONE STRIKE IN THE GULF OF FINLAND AND DRIFTED "
                 "INTO FINNISH WATERS."),
        "motif": "ship",
    },
    {
        "tag": "SEOUL",
        "headline": "MINISTER QUITS OVER AI EXAM CHEATING",
        "body": ("EDUCATION MINISTER CHOI KYO-JIN RESIGNED AFTER A TOP "
                 "SCORER CONFESSED TO CHEATING WITH A HIDDEN CAMERA AND "
                 "AI. 111 CASES FOUND AT THE SUNEUNG."),
        "motif": "exam",
    },
    {
        "tag": "SOUTH ASIA",
        "headline": "NEPAL PM SHAH MEETS MODI IN DELHI",
        "body": ("NEPAL PM BALENDRA SHAH HELD BILATERAL TALKS WITH PM "
                 "MODI ON HIS FIRST VISIT TO INDIA SINCE TAKING OFFICE "
                 "IN MARCH."),
        "motif": "flags",
    },
    {
        "tag": "INDONESIA",
        "headline": "FACTORY FIRE - 7 DEAD, 50 MISSING",
        "body": ("FIRE SWEPT THE PT FONUSA AGUNG MULIA CANDY FACTORY IN "
                 "BANTEN. SEVEN BODIES RECOVERED, 50 WORKERS STILL "
                 "MISSING."),
        "motif": "factory",
    },
]

TICKER = ("LISBON MARCHES OVER LIVING COSTS * FBI DATABASE HACKED * "
          "BOLSONARO IN ICU * INDIA 720/9D IN WELLINGTON")

FOOTER = "ALL STORIES REPORTED ON 23 NOVEMBER 2026 - DRAWN ENTIRELY IN CODE"


# ---------------------------------------------------------------------------
# Page layout. Everything is placed from measured text widths, never from
# guesses: a line is drawn only after wrap_text has said it fits.
# ---------------------------------------------------------------------------

MARGIN = 40
CONTENT_W = WIDTH - 2 * MARGIN


def draw_masthead(board):
    draw_centred(board, WIDTH // 2, 44, "THE WORLD IN ONE IMAGE", 5, INK)
    board.hline(MARGIN, WIDTH - MARGIN, 112, INK, 3)
    draw_centred(board, WIDTH // 2, 122,
                 "MONDAY - 23 NOVEMBER 2026 - WORLD EDITION", 2, INK)
    board.hline(MARGIN, WIDTH - MARGIN, 152, INK, 2)
    board.hline(MARGIN, WIDTH - MARGIN, 157, INK, 1)


def draw_lead(board):
    top = 172
    draw_text(board, MARGIN, top, LEAD["kicker"], 2, RED)
    head_lines = wrap_text(LEAD["headline"], 4, 660)
    y = top + 30
    for line in head_lines:
        draw_text(board, MARGIN, y, line, 4, INK)
        y += 48
    body_lines = wrap_text(LEAD["body"], 2, 660)
    y += 6
    for line in body_lines:
        draw_text(board, MARGIN, y, line, 2, INK)
        y += 26
    MOTIFS[LEAD["motif"]](board, 760, top + 6, 190, RED)
    board.hline(MARGIN, WIDTH - MARGIN, 428, INK, 2)


def draw_tile(board, tile, x, y, w, h):
    board.frame(x, y, w, h, INK, 1)
    motif_size = 64
    mx = x + w - motif_size - 12
    my = y + 10
    MOTIFS[tile["motif"]](board, mx, my, motif_size, BLUE)
    head_w = w - motif_size - 30
    draw_text(board, x + 12, y + 10, tile["tag"], 1, RED)
    head_lines = wrap_text(tile["headline"], 2, head_w)
    ty = y + 30
    for line in head_lines[:2]:
        draw_text(board, x + 12, ty, line, 2, INK)
        ty += 26
    body_lines = wrap_text(tile["body"], 1, w - 24)
    by = y + 88
    for line in body_lines[:4]:
        draw_text(board, x + 12, by, line, 1, INK)
        by += 14


def draw_grid(board):
    tile_w = (CONTENT_W - 16) // 2
    tile_h = 148
    gap = 16
    y = 444
    for row in range(3):
        for col in range(2):
            tile = TILES[row * 2 + col]
            x = MARGIN + col * (tile_w + gap)
            draw_tile(board, tile, x, y, tile_w, tile_h)
        y += tile_h + 6


def draw_ticker(board):
    board.fill_rect(MARGIN, 910, CONTENT_W, 66, INK)
    draw_centred(board, WIDTH // 2, 934, TICKER, 1, PAPER)
    draw_centred(board, WIDTH // 2, 990, FOOTER, 1, GREY)


def compose():
    board = Board(WIDTH, HEIGHT, PAPER)
    board.frame(14, 14, WIDTH - 28, HEIGHT - 28, INK, 2)
    board.frame(20, 20, WIDTH - 40, HEIGHT - 40, INK, 1)
    draw_masthead(board)
    draw_lead(board)
    draw_grid(board)
    draw_ticker(board)
    return board


def main():
    board = compose()
    data = board.png_bytes()
    with open(OUT_PATH, "wb") as fh:
        fh.write(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"wrote {OUT_PATH}: {len(data)} bytes, sha256 {digest}")
    assert len(data) <= 1024 * 1024, "PNG over 1 MiB"
    return 0


if __name__ == "__main__":
    sys.exit(main())
