#!/usr/bin/env python3
"""Render terminal-style animations for the BootLab README and walkthrough.

Uses only the Python standard library and Pillow.  Generates dark/light GIFs with
static PNG fallbacks for prefers-reduced-motion.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Sequence

from PIL import GifImagePlugin, Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "animations"
PALETTES = {
    "dark": {
        "bg": "#09141c",
        "bar": "#0d1c27",
        "panel": "#0c1822",
        "line": "#304e5e",
        "grid": "#1b3645",
        "fg": "#eee9db",
        "secondary": "#b7cbd0",
        "muted": "#85a7b7",
        "dim": "#4f7285",
        "accent": "#e7b26b",
        "blue": "#8bb8cb",
        "green": "#a9bfae",
        "good": "#7bd67b",
        "bad": "#d67b7b",
        "red": "#d67b7b",
    },
    "light": {
        "bg": "#f3efe5",
        "bar": "#e9e5d9",
        "panel": "#f8f5ec",
        "line": "#a4b5b7",
        "grid": "#d8dfda",
        "fg": "#12354e",
        "secondary": "#274c5f",
        "muted": "#516c78",
        "dim": "#8a9ca1",
        "accent": "#925e1a",
        "blue": "#34697d",
        "green": "#426451",
        "good": "#2d7a2d",
        "bad": "#a63c3c",
        "red": "#a63c3c",
    },
}


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def smooth(x: float) -> float:
    x = clamp(x)
    return x * x * (3 - 2 * x)


def rgba(v: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return tuple(int(v[i : i + 2], 16) for i in (1, 3, 5)) + (alpha,)


def mix(a: str, b: str, q: float) -> str:
    q = clamp(q)
    aa, bb = rgba(a), rgba(b)
    return "#" + "".join(f"{round(aa[i] + (bb[i] - aa[i]) * q):02x}" for i in range(3))


def find_font(bold: bool = False, requested: str | None = None) -> str:
    if requested:
        p = Path(requested).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Font not found: {p}")
        return str(p)
    filename = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / filename,
        Path("/usr/local/share/fonts") / filename,
        Path.home() / ".local/share/fonts" / filename,
        Path.home() / "Library/Fonts" / filename,
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    raise FileNotFoundError("Install DejaVu Sans Mono or pass --font and --bold-font.")


class Renderer:
    def __init__(
        self,
        theme: str,
        mobile: bool,
        font: str,
        bold_font: str,
        w: int,
        h: int,
        title: str,
        scale: int = 2,
    ):
        self.theme = theme
        self.mobile = mobile
        self.p = PALETTES[theme]
        self.scale = scale
        self.font_path = font
        self.bold_path = bold_font
        self.w, self.h = w, h
        self.title = title
        self.fonts: dict[tuple[float, bool], ImageFont.FreeTypeFont] = {}
        self.bar_h = 44

    def font(self, size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(
                self.bold_path if bold else self.font_path, round(size * self.scale)
            )
        return self.fonts[key]

    def draw(self, im: Image.Image) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(im)

    def text(
        self,
        im: Image.Image,
        x: float,
        y: float,
        value: str,
        size: float = 16,
        color: str = "fg",
        bold: bool = False,
        anchor: str = "ls",
        opacity: float = 1.0,
    ) -> None:
        fill = self.p.get(color, color)
        if opacity != 1:
            fill = mix(self.p["panel"], fill, opacity)
        self.draw(im).text(
            (round(x * self.scale), round(y * self.scale)),
            value,
            font=self.font(size, bold),
            fill=fill,
            anchor=anchor,
            stroke_width=0,
        )

    def text_width(self, value: str, size: float, bold: bool = False) -> float:
        return self.font(size, bold).getlength(value) / self.scale

    def line(
        self,
        im: Image.Image,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str = "line",
        width: float = 1,
    ) -> None:
        self.draw(im).line(
            tuple(round(v * self.scale) for v in (x1, y1, x2, y2)),
            fill=self.p.get(color, color),
            width=max(1, round(width * self.scale)),
        )

    def rect(
        self,
        im: Image.Image,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str | None = None,
        outline: str | None = None,
        radius: float = 0,
        width: float = 1,
    ) -> None:
        fill = self.p.get(fill, fill)
        outline = self.p.get(outline, outline)
        box = tuple(round(v * self.scale) for v in (x, y, x + w, y + h))
        if radius:
            self.draw(im).rounded_rectangle(
                box,
                radius=round(radius * self.scale),
                fill=fill,
                outline=outline,
                width=max(1, round(width * self.scale)),
            )
        else:
            self.draw(im).rectangle(
                box,
                fill=fill,
                outline=outline,
                width=max(1, round(width * self.scale)),
            )

    def dot(self, im: Image.Image, x: float, y: float, r: float, color: str = "accent") -> None:
        self.draw(im).ellipse(
            tuple(round(v * self.scale) for v in (x - r, y - r, x + r, y + r)),
            fill=self.p.get(color, color),
        )

    def terminal_base(self) -> Image.Image:
        im = Image.new("RGB", (self.w * self.scale, self.h * self.scale), self.p["bg"])
        self.rect(im, 1, 1, self.w - 2, self.h - 2, None, "line", radius=8)
        self.rect(im, 2, 2, self.w - 4, self.bar_h - 2, "bar", radius=6)
        self.line(im, 1, self.bar_h, self.w - 1, self.bar_h)
        self.dot(im, 22, 23, 4, "accent")
        self.text(im, 36, 28, "bootlab@lab : ~/secure-update", 13, "secondary", True)
        if not self.mobile:
            self.text(im, self.w - 22, 28, self.title.upper(), 12, "muted", anchor="rs")
        return im

    def panel(
        self,
        im: Image.Image,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str | None = None,
    ) -> None:
        self.rect(im, x, y, w, h, "panel", "line", radius=4, width=1)
        if label:
            lw = self.text_width(label, 12) + 16
            self.rect(im, x + 12, y - 10, lw, 20, "bg")
            self.text(im, x + 20, y + 2, label, 12, "muted")

    def arrow(self, im: Image.Image, x1: float, y1: float, x2: float, y2: float, color: str = "accent") -> None:
        self.line(im, x1, y1, x2, y2, color, 1.5)
        angle = math.atan2(y2 - y1, x2 - x1)
        for d in (math.pi - 0.5, math.pi + 0.5):
            ax = x2 + 6 * math.cos(angle + d)
            ay = y2 + 6 * math.sin(angle + d)
            self.line(im, ax, ay, x2, y2, color, 1.5)

    def checkmark(self, im: Image.Image, x: float, y: float, size: float, color: str = "good") -> None:
        s = size
        pts = [(x - s * 0.4, y - s * 0.1), (x - s * 0.1, y + s * 0.25), (x + s * 0.45, y - s * 0.35)]
        for i in range(len(pts) - 1):
            self.line(im, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], color, 2.5)

    def xmark(self, im: Image.Image, x: float, y: float, size: float, color: str = "bad") -> None:
        s = size
        self.line(im, x - s / 2, y - s / 2, x + s / 2, y + s / 2, color, 2.5)
        self.line(im, x + s / 2, y - s / 2, x - s / 2, y + s / 2, color, 2.5)

    # All scenes are explanatory schematics, never generated test evidence.
    def finish(self, im: Image.Image) -> Image.Image:
        return im.resize((self.w, self.h), Image.Resampling.LANCZOS)

    def intro(self, im, number, title, description):
        self.text(im, 30, 81, number, 15, "accent", True)
        self.text(im, 72, 82, title, 25, "fg", True)
        self.text(im, 30, 112, description, 14, "muted")

    def footer(self, im, text, t, duration=10, tag="CONCEPTUAL VIEW"):
        y = self.h - 49
        self.line(im, 1, y, self.w - 1, y)
        self.text(im, 24, y + 28, text, 12, "secondary")
        self.text(im, self.w - 24, y + 28, tag, 11, "muted", anchor="rs")
        self.line(im, 2, self.h - 3, self.w - 2, self.h - 3, "grid", 2)
        self.line(im, 2, self.h - 3, 2 + (self.w - 4) * clamp(t / duration), self.h - 3, "accent", 2)

    def node(self, im, x, y, w, h, title, detail="", active=False, color="accent", size=17):
        fill = mix(self.p["panel"], self.p[color], .10 if active else 0)
        self.rect(im, x, y, w, h, fill, color if active else "line", radius=3, width=2 if active else 1)
        self.text(im, x + w / 2, y + h / 2 - (6 if detail else -5), title, size, "fg", True, anchor="ms")
        if detail:
            self.text(im, x + w / 2, y + h / 2 + 17, detail, 12, color if active else "muted", anchor="ms")

    def pill(self, im, x, y, label, color="accent", size=11):
        w = self.text_width(label, size, True) + 20
        self.rect(im, x, y, w, 25, mix(self.p["panel"], self.p[color], .11), color, radius=3)
        self.text(im, x + 10, y + 17, label, size, color, True)

    def flow(self, im, points, q, color="accent"):
        for a, b in zip(points, points[1:]):
            self.line(im, *a, *b, "line", 1.5)
        self.arrow(im, *points[-2], *points[-1], "line")
        if not 0 <= q <= 1:
            return
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        distance = smooth(q) * sum(lengths)
        for (a, b), length in zip(zip(points, points[1:]), lengths):
            if distance <= length:
                u = distance / length if length else 1
                x, y = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
                self.dot(im, x, y, 6, mix(self.p["bg"], self.p[color], .25))
                self.dot(im, x, y, 3, color)
                break
            distance -= length

    def chip_icon(self, im, x, y, color="accent"):
        self.rect(im, x + 8, y + 8, 28, 28, None, color, width=1.5)
        self.rect(im, x + 14, y + 14, 16, 16, None, "line")
        for n in (14, 22, 30):
            self.line(im, x + n, y + 2, x + n, y + 8, color)
            self.line(im, x + n, y + 36, x + n, y + 42, color)
            self.line(im, x + 2, y + n, x + 8, y + n, color)
            self.line(im, x + 36, y + n, x + 42, y + n, color)

    def lock_icon(self, im, x, y, color="accent"):
        self.rect(im, x + 10, y + 19, 25, 22, None, color, radius=2, width=1.5)
        self.draw(im).arc(tuple(round(v * self.scale) for v in (x + 15, y + 3, x + 30, y + 30)), 180, 360, fill=self.p[color], width=round(1.5 * self.scale))
        self.dot(im, x + 22.5, y + 28, 2, color)
        self.line(im, x + 22.5, y + 29, x + 22.5, y + 34, color, 1.5)

    def header_frame(self, t):
        im = self.terminal_base()
        groups = [("P", "Boot / update", 6), ("S", "Image rejection", 6), ("V", "Version policy", 2), ("F", "Reset recovery", 6), ("A", "Algorithms", 10), ("K", "Key selection", 3)]
        active = min(5, int(max(0, t - .8) / 1.3))
        if self.mobile:
            self.panel(im, 20, 67, 520, 205, "01 / SECURE FIRMWARE UPDATES")
            self.text(im, 42, 125, "BootLab", 42, "fg", True)
            self.text(im, 42, 158, "Test the update. Read the evidence.", 17, "blue")
            self.text(im, 42, 195, "MCUboot simulator + imgtool", 15, "secondary")
            self.text(im, 42, 226, "Authenticity / recovery / provenance", 14, "muted")
            self.panel(im, 20, 299, 520, 284, "02 / 33 SCENARIO DEFINITIONS")
            for i, (prefix, label, count) in enumerate(groups):
                y = 331 + i * 39
                self.text(im, 40, y, prefix, 14, "accent" if i == active else "muted", True)
                self.text(im, 68, y, label, 14, "fg")
                for n in range(count):
                    self.rect(im, 280 + n * 19, y - 12, 12, 15, mix(self.p["panel"], self.p["accent" if i == active else "blue"], .35), "accent" if i == active else "line", radius=1)
                self.text(im, 514, y, str(count), 14, "muted", anchor="rs")
            self.text(im, 26, 616, "$ bootlab run-matrix", 17, "secondary")
            self.text(im, 26, 646, "Illustrative coverage; inspect run evidence.", 12, "muted")
            self.line(im, 20, 669, 20 + 520 * clamp(t / 10), 669, "accent", 2)
            return self.finish(im)
        self.panel(im, 25, 74, 465, 269, "01 / SECURE FIRMWARE UPDATES")
        self.text(im, 49, 146, "BootLab", 49, "fg", True)
        self.text(im, 50, 184, "Test the update.", 25, "blue")
        self.text(im, 50, 216, "Read the evidence.", 25, "blue")
        self.text(im, 50, 258, "MCUboot simulator + imgtool", 16, "secondary")
        self.text(im, 50, 290, "Repeatable cases. Inspectable records.", 14, "muted")
        self.panel(im, 512, 74, 423, 269, "02 / 33 SCENARIO DEFINITIONS")
        for i, (prefix, label, count) in enumerate(groups):
            y = 112 + i * 38
            self.text(im, 530, y, prefix, 13, "accent" if i == active else "muted", True)
            self.text(im, 552, y, label, 13, "fg")
            for n in range(count):
                self.rect(im, 713 + n * 17, y - 12, 10, 15, mix(self.p["panel"], self.p["accent" if i == active else "blue"], .35), "accent" if i == active else "line", radius=1)
            self.text(im, 915, y, str(count), 13, "muted", anchor="rs")
        for i, (label, detail) in enumerate([("AUTHENTICITY", "signed images + negative cases"), ("RECOVERY", "swap / overwrite / reset"), ("EVIDENCE", "logs + verdict + provenance")]):
            x = 25 + i * 310
            self.panel(im, x, 369, 290, 87)
            (self.lock_icon if i == 0 else self.chip_icon)(im, x + 12, 385, "accent" if i == active % 3 else "blue")
            self.text(im, x + 67, 401, label, 15, "secondary", True)
            # Split deliberately for legibility at README display width.
            parts = detail.split(" + ") if " + " in detail else ["swap / overwrite", "reset simulation"]
            self.text(im, x + 67, 424, parts[0], 11, "muted")
            self.text(im, x + 67, 442, " + ".join(parts[1:]), 11, "muted")
        self.footer(im, "$ bootlab run-matrix", t, tag="ILLUSTRATIVE COVERAGE / NOT A RUN RESULT")
        return self.finish(im)

    def lifecycle_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "01", "Where the update decisions happen", "A conceptual map: image checks, configured policy, update mode and boot outcome.")
        titles = [("IMAGE", "candidate + metadata"), ("VERIFY", "layout / hash / key"), ("POLICY", "configured version rule"), ("UPDATE", "selected boot mode")]
        step = min(3, int(t / 2))
        for i, (title, detail) in enumerate(titles):
            x = 30 + i * 232
            self.node(im, x, 158, 204, 86, title, detail, step == i)
            if i < 3:
                self.flow(im, [(x + 204, 201), (x + 232, 201)], (t - i * 2 - 1) / .8)
        self.flow(im, [(828, 244), (828, 291), (283, 291), (283, 326)], (t - 6) / 1.4)
        self.flow(im, [(828, 244), (828, 291), (713, 291), (713, 326)], (t - 6) / 1.4)
        self.node(im, 90, 326, 385, 85, "SWAP", "trial -> confirm or revert", t >= 7, "blue", 20)
        self.node(im, 510, 326, 385, 85, "OVERWRITE", "replace primary; no swap-back copy", t >= 7, "accent", 20)
        self.text(im, 30, 447, "Failed image checks reject the candidate; policy behavior depends on the build.", 13, "muted")
        self.footer(im, "Follow the decision, then inspect the matching scenario.", t)
        return self.finish(im)

    def verification_frame(self, t):
        im = self.terminal_base()
        case = min(2, int(t / 3))
        self.intro(im, "02", "An image must pass more than one check", "Conceptual validation gates; imgtool verification and MCUboot tests provide different evidence.")
        self.panel(im, 30, 154, 312, 132, "SIGNED IMAGE")
        for i, (label, w) in enumerate([("HEADER", 68), ("PAYLOAD", 126), ("TLVs", 64)]):
            x = 46 + [0, 74, 206][i]
            color = "bad" if case == 1 and i == 1 else "blue"
            self.rect(im, x, 185, w, 50, mix(self.p["panel"], self.p[color], .10), color)
            self.text(im, x + w / 2, 215, label, 12, color, True, anchor="ms")
        self.text(im, 47, 263, ["unchanged signed bytes", "one payload byte changed", "signed by another key"][case], 13, "bad" if case else "secondary")
        self.flow(im, [(342, 217), (388, 217)], (t % 3) / .7)
        self.node(im, 388, 173, 235, 88, "VERIFY", "format -> hash -> signature", .6 <= t % 3 <= 2.5, "accent", 22)
        self.flow(im, [(623, 217), (666, 217)], (t % 3 - .8) / .7)
        self.node(im, 666, 173, 264, 88, "ACCEPT" if case == 0 else "REJECT", ["matches expected signer", "integrity check fails", "expected key does not match"][case], t % 3 >= 1.4, "good" if case == 0 else "bad", 24)
        self.text(im, 505, 293, "verification key supplied by the test", 12, "muted", anchor="ms")
        self.arrow(im, 505, 282, 505, 263, "blue")
        rows = [("Intact image + expected key", "accept", "good"), ("Changed payload", "reject", "bad"), ("Different signing key", "reject", "bad")]
        for i, (label, verdict, color) in enumerate(rows):
            y = 326 + i * 43
            self.rect(im, 30, y, 900, 37, mix(self.p["panel"], self.p[color], .06) if case == i else "panel", color if case == i else "line", radius=2)
            self.text(im, 48, y + 25, label, 14, "secondary")
            self.text(im, 908, y + 25, verdict.upper(), 13, color, True, anchor="rs")
        self.footer(im, "A valid signature is separate from version policy.", t)
        return self.finish(im)

    def slot(self, im, x, y, label, version, color, highlight=False):
        self.text(im, x, y + 22, label, 12, "muted")
        self.rect(im, x + 100, y, 262, 43, mix(self.p["panel"], self.p[color], .10), color if highlight else "line", radius=2, width=2 if highlight else 1)
        if version:
            self.text(im, x + 116, y + 28, version, 16, color, True)
            for n in range(6):
                self.rect(im, x + 218 + n * 20, y + 11, 12, 21, mix(self.p["panel"], self.p[color], .45), None)

    def swap_overwrite_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "03", "Two ways to replace the primary image", "A simplified sector exchange explains the storage trade-off; exact flash order is port-dependent.")
        self.panel(im, 30, 154, 438, 285, "SWAP WITH SCRATCH")
        self.panel(im, 492, 154, 438, 285, "OVERWRITE")
        phase = min(3, int(t / 2.4))
        states = [("old A", "new B", ""), ("old A", "new B", "old A"), ("new B", "new B", "old A"), ("new B", "old A", "")]
        left = states[phase]
        for i, (label, value) in enumerate(zip(["primary", "secondary", "scratch"], left)):
            self.slot(im, 50, 196 + i * 64, label, value, "accent" if "new" in value else "blue", phase == i + 1 or (phase == 3 and i < 2))
        if phase == 1:
            self.flow(im, [(429, 217), (447, 217), (447, 345), (429, 345)], (t - 2.4) / 2.2, "blue")
        elif phase == 2:
            self.flow(im, [(429, 281), (447, 281), (447, 217), (429, 217)], (t - 4.8) / 2.2)
        elif phase == 3:
            self.flow(im, [(429, 345), (447, 345), (447, 281), (429, 281)], (t - 7.2) / 2.2, "blue")
        self.text(im, 50, 410, ["01 / choose a sector", "02 / preserve old data in scratch", "03 / copy new data into primary", "04 / restore old data to secondary"][phase], 12, "secondary")
        for i, (label, value) in enumerate([("primary", "new B" if phase >= 2 else "old A"), ("secondary", "new B")]):
            self.slot(im, 512, 196 + i * 64, label, value, "accent" if "new" in value else "blue", phase >= 2 and i == 0)
        self.flow(im, [(891, 281), (909, 281), (909, 217), (891, 217)], (t - 4.8) / 2.2)
        self.pill(im, 611, 328, "NO OLD-IMAGE FALLBACK", "muted")
        self.text(im, 512, 410, "New data replaces old primary data.", 12, "secondary")
        self.footer(im, "One sector shown; the operation repeats across the image.", t)
        return self.finish(im)

    def trial_revert_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "04", "A trial boot is a decision point", "Swap can retain the old image while the new application decides whether to confirm.")
        self.node(im, 30, 235, 195, 91, "TRIAL v2", "old v1 retained", t < 3, "accent", 23)
        self.flow(im, [(225, 280), (265, 280), (265, 202), (305, 202)], (t - 1) / 2, "good")
        self.flow(im, [(225, 280), (265, 280), (265, 367), (305, 367)], (t - 5) / 1.5, "blue")
        self.node(im, 305, 160, 240, 85, "APP CONFIRMS", "image marked successful", 2 <= t < 5, "good", 18)
        self.flow(im, [(545, 202), (624, 202)], (t - 3) / 1.2, "good")
        self.node(im, 624, 160, 306, 85, "v2 PERSISTS", "subsequent boot keeps new image", t >= 4, "good", 22)
        self.node(im, 305, 325, 240, 85, "NO CONFIRMATION", "reset before confirmation", 6 <= t < 8, "blue", 18)
        self.flow(im, [(545, 367), (624, 367)], (t - 7) / 1.2, "blue")
        self.node(im, 624, 325, 306, 85, "REVERT TO v1", "old authenticated image restored", t >= 8, "blue", 22)
        self.pill(im, 624, 259, "P04 / CONFIRM-PERSIST", "good")
        self.pill(im, 624, 424, "P03 / TRIAL-REVERT", "blue")
        self.footer(im, "P03: basic_revert / P04: norevert (upstream proxies).", t)
        return self.finish(im)

    def fault_injection_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "05", "Interrupt, restart, then inspect recovery", "The simulator injects a software interruption at a counted flash operation.")
        labels = [("WRITE", "update state"), ("CUT", "before an operation"), ("RESTART", "boot again"), ("RESUME", "use saved state"), ("CHECK", "assert final image")]
        active = min(4, int(t / 1.9))
        for i, (label, detail) in enumerate(labels):
            x = 30 + i * 183
            self.node(im, x, 160, 168, 85, label, detail, i == active, "bad" if i == 1 else "accent", 18)
            if i < 4:
                self.flow(im, [(x + 168, 203), (x + 183, 203)], (t - i * 1.9 - .8) / .8, "bad" if i == 0 else "accent")
        self.panel(im, 30, 292, 440, 149, "PERSISTENT FLASH STATE")
        for i in range(10):
            color = "blue" if i < 3 else "accent" if active >= 3 and i < min(10, 3 + int((t - 5.7) * 2)) else "line"
            self.rect(im, 51 + i * 39, 323, 29, 40, mix(self.p["panel"], self.p[color], .22), color, radius=2)
        self.text(im, 51, 393, "Completed work + update metadata", 15, "secondary")
        self.text(im, 51, 421, "Progress blocks are schematic, not a trace.", 12, "muted")
        self.panel(im, 492, 292, 438, 149, "WHAT THE TEST CAN SUPPORT")
        self.text(im, 512, 329, "Does the resumed update converge?", 16, "fg", True)
        self.text(im, 512, 363, "Inspect the selected test and its assertions.", 12, "secondary")
        self.text(im, 512, 394, "FAULT_INDEX=0 disables injection.", 13, "accent")
        self.text(im, 512, 421, "Physical power-cut testing is separate.", 12, "muted")
        self.footer(im, "Operation count is not a verified sector or trailer phase.", t, tag="SIMULATOR SCHEMATIC")
        return self.finish(im)

    def algorithms_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "06", "Keep the questions; vary the signature scheme", "The same lab structure covers ECDSA-P256, RSA-2048 and Ed25519 configurations.")
        configs = [("ECDSA-P256", "sig-ecdsa", "P / S / F reference cases"), ("RSA-2048", "sig-rsa", "A01 A03 A05 A07 A09"), ("Ed25519", "sig-ed25519", "A02 A04 A06 A08 A10")]
        step = min(3, int(t / 2.4))
        for i, (label, feature, cases) in enumerate(configs):
            x = 30 + i * 306
            self.panel(im, x, 156, 288, 286, f"0{i + 1} / CONFIGURATION")
            self.lock_icon(im, x + 18, 181, "blue")
            self.text(im, x + 77, 209, label, 22, "fg", True)
            self.text(im, x + 77, 236, feature, 14, "blue")
            self.line(im, x + 18, 259, x + 270, 259)
            for j, text in enumerate(["build signed fixtures", "exercise selected tests", "reject bad images", "record evidence"]):
                y = 287 + j * 31
                self.dot(im, x + 25, y - 5, 3, "accent" if step == j else "line")
                self.text(im, x + 42, y, text, 13, "fg" if step == j else "muted", step == j)
            self.text(im, x + 18, 426, cases, 11, "secondary")
        self.footer(im, "Coverage comparison; no speed or security ranking is implied.", t)
        return self.finish(im)

    def key_lifecycle_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "07", "Rotation scenarios select a verification key", "K01-K03 call imgtool with an explicit key; they do not update a device trust store.")
        for x, label in [(48, "CASE / IMAGE SIGNER"), (393, "VERIFICATION KEY"), (746, "EXPECTED RESULT")]:
            self.text(im, x, 164, label, 12, "muted", True)
        rows = [("K01", "dev-trusted-2", "dev-trusted-2", "ACCEPT", "good"), ("K02", "dev-trusted", "dev-trusted-2", "REJECT", "bad"), ("K03", "dev-untrusted", "dev-trusted-2", "REJECT", "bad")]
        active = min(2, int(t / 3))
        for i, (case, signer, key, verdict, color) in enumerate(rows):
            y = 187 + i * 80
            self.rect(im, 30, y, 900, 66, "panel", color if i == active else "line", radius=3, width=2 if i == active else 1)
            self.text(im, 48, y + 39, case, 15, "accent", True)
            self.text(im, 105, y + 39, signer, 16, "secondary")
            self.flow(im, [(293, y + 33), (365, y + 33)], (t - i * 3) / 1.4, color)
            self.text(im, 393, y + 39, key, 17, "blue", True)
            self.flow(im, [(586, y + 33), (713, y + 33)], (t - i * 3 - 1.2) / 1.4, color)
            self.text(im, 761, y + 40, verdict, 19, color, True)
        self.text(im, 30, 455, "Key labels describe fixture roles; device provisioning and revocation need separate tests.", 12, "muted")
        self.footer(im, "Expected key must match the image signer.", t, tag="IMGTOOL KEY-SELECTION MODEL")
        return self.finish(im)

    def evidence_frame(self, t):
        im = self.terminal_base()
        self.intro(im, "08", "Make every verdict inspectable", "Read the scenario, the executed backend and the oracle together before drawing a conclusion.")
        step = min(4, int(t / 1.8))
        nodes = [("YAML", "scenario intent"), ("BACKEND", "cargo / imgtool"), ("ORACLE", "lab assertions"), ("RECORD", "JSON + raw logs"), ("REPORT", "review findings")]
        for i, (label, detail) in enumerate(nodes):
            x = 30 + i * 183
            self.node(im, x, 159, 168, 82, label, detail, i == step, "accent", 18)
            if i < 4:
                self.flow(im, [(x + 168, 200), (x + 183, 200)], (t - i * 1.8 - .7) / .8)
        self.panel(im, 30, 288, 440, 158, "evidence/<case-id>/")
        for i, (label, detail) in enumerate([("record.json", "verdict + configuration"), ("stdout.txt", "captured standard output"), ("stderr.txt", "captured diagnostics")]):
            y = 328 + i * 40
            self.text(im, 51, y, label, 16, "blue", True)
            self.text(im, 205, y, detail, 12, "secondary")
        self.panel(im, 492, 288, 438, 158, "READ THE EVIDENCE BOUNDARY")
        self.text(im, 513, 328, "OBSERVED", 13, "accent", True)
        self.text(im, 627, 328, "exit status + logs + test counts", 12, "secondary")
        self.text(im, 513, 368, "DECLARED", 13, "blue", True)
        self.text(im, 627, 368, "expected states in scenario YAML", 12, "secondary")
        self.text(im, 513, 408, "REVIEW", 13, "muted", True)
        self.text(im, 627, 408, "proxy coverage + oracle limits", 12, "secondary")
        self.footer(im, "A passing wrapper verdict is one piece of evidence.", t, tag="EVIDENCE FLOW")
        return self.finish(im)

    def export(self, name, duration, fps, frame_fn, poster_time=0, poster_only=False):
        ASSETS.mkdir(parents=True, exist_ok=True)
        stem = f"{name}-{self.theme}{'-mobile' if self.mobile else ''}"
        poster = frame_fn(poster_time)
        poster.save(ASSETS / f"{stem}.png", optimize=True)
        if poster_only:
            print(f"{stem}: poster", flush=True)
            return
        # Sample every narrative beat into one palette, preserving all accent colors.
        swatches = Image.new("RGB", (320 * 5, 180 * 2), self.p["bg"])
        for n in range(10):
            sample = frame_fn(duration * n / 10)
            sample.thumbnail((320, 180), Image.Resampling.LANCZOS)
            swatches.paste(sample, ((n % 5) * 320, (n // 5) * 180))
        palette = swatches.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        frames = []
        for n in range(round(duration * fps)):
            frames.append(frame_fn(n / fps).quantize(palette=palette, dither=Image.Dither.NONE))
        path = ASSETS / f"{stem}.gif"
        save_delta_gif(frames, path, round(1000 / fps))
        # Decode every frame: disposal/transparency must never leave stale pixels.
        with Image.open(path) as decoded:
            assert decoded.n_frames == len(frames), path
            total = 0
            for n, expected in enumerate(frames):
                decoded.seek(n)
                assert ImageChops.difference(decoded.convert("RGB"), expected.convert("RGB")).getbbox() is None, (path, n)
                total += decoded.info.get("duration", 0)
            assert total == round(duration * 1000), (path, total)
            assert decoded.info.get("loop") == 0, path
        print(f"{stem}: {len(frames)} frames verified, {path.stat().st_size:,} bytes", flush=True)


def save_delta_gif(frames: Sequence[Image.Image], path: Path, duration_ms: int) -> None:
    """Write palette-stable transparent deltas, reserving index 255.

    The Pillow operations keep delta detection in C rather than scanning pixels
    in Python. Each encoded frame is checked after export against its source.
    """
    if not frames or any(f.mode != "P" or f.size != frames[0].size for f in frames):
        raise ValueError("Equally sized palette images are required")
    if duration_ms < 10 or duration_ms % 10:
        raise ValueError("GIF frame duration must be a positive multiple of 10 ms")
    palette = frames[0].getpalette()
    temp = path.with_suffix(".gif.tmp")
    prev = None
    with temp.open("wb") as out:
        header, _ = GifImagePlugin.getheader(frames[0], info={"loop": 0, "version": b"GIF89a"})
        for block in header:
            out.write(block)
        for frame in frames:
            if frame.getextrema()[1] >= 255 or frame.getpalette() != palette:
                raise ValueError("Frames must share a palette and reserve index 255")
            # Converting indices via frombytes keeps differences in index space.
            indices = Image.frombytes("L", frame.size, frame.tobytes())
            if prev is None:
                tile, offset = frame.copy(), (0, 0)
            else:
                delta = ImageChops.difference(indices, prev)
                box = delta.getbbox()
                if box:
                    tile = frame.crop(box)
                    unchanged = delta.crop(box).point(lambda v: 0 if v else 255)
                    tile.paste(255, mask=unchanged)
                    offset = box[:2]
                else:
                    tile, offset = Image.new("P", (1, 1), 255), (0, 0)
                tile.putpalette(palette)
            for block in GifImagePlugin.getdata(tile, offset=offset, duration=duration_ms, disposal=1, transparency=255, include_color_table=False):
                out.write(block)
            prev = indices
        out.write(b";")
    temp.replace(path)


# name, mobile, width, height, terminal label, duration, fps, poster time
SPECS = [
    ("header", False, 960, 530, "Secure boot / OTA assurance lab", 10, 20, 9.5),
    ("header", True, 560, 690, "Secure boot / OTA assurance lab", 10, 20, 9.5),
    ("lifecycle", False, 960, 530, "01 / update decisions", 10, 20, 9.5),
    ("verification", False, 960, 530, "02 / image verification", 10, 20, 9.5),
    ("swap-overwrite", False, 960, 530, "03 / flash update modes", 10, 20, 9.5),
    ("trial-revert", False, 960, 530, "04 / trial + confirmation", 10, 20, 9.5),
    ("fault-injection", False, 960, 530, "05 / reset recovery", 10, 20, 9.5),
    ("algorithms", False, 960, 530, "06 / signature configurations", 10, 20, 9.5),
    ("key-lifecycle", False, 960, 530, "07 / key selection", 10, 20, 9.5),
    ("evidence", False, 960, 530, "08 / evidence trail", 10, 20, 9.5),
]


def write_manifest():
    entries = []
    for spec in SPECS:
        name, mobile, w, h, title, duration, fps, poster_time = spec
        for theme in PALETTES:
            stem = f"{name}-{theme}{'-mobile' if mobile else ''}"
            gif, png = ASSETS / f"{stem}.gif", ASSETS / f"{stem}.png"
            if not gif.exists() or not png.exists():
                continue
            with Image.open(gif) as im:
                total = 0
                for frame in range(im.n_frames):
                    im.seek(frame)
                    total += im.info.get("duration", 0)
                entries.append({"scene": name, "theme": theme, "mobile": mobile, "gif": gif.name, "poster": png.name, "width": im.width, "height": im.height, "frames": im.n_frames, "duration_ms": total, "gif_bytes": gif.stat().st_size, "poster_bytes": png.stat().st_size})
    (ASSETS / "manifest.json").write_text(json.dumps({"purpose": "Explanatory schematics, not test evidence", "assets": entries}, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--theme", choices=["dark", "light", "all"], default="all")
    ap.add_argument("--layout", choices=["desktop", "mobile", "all"], default="all")
    ap.add_argument("--name", choices=list(dict.fromkeys(s[0] for s in SPECS)) + ["all"], default="all")
    ap.add_argument("--font")
    ap.add_argument("--bold-font")
    ap.add_argument("--posters-only", action="store_true")
    args = ap.parse_args()
    font, bold = find_font(False, args.font), find_font(True, args.bold_font or args.font)
    for spec in SPECS:
        name, mobile, w, h, title, duration, fps, poster = spec
        if args.name not in (name, "all") or (args.layout != "all" and mobile != (args.layout == "mobile")):
            continue
        for theme in (["dark", "light"] if args.theme == "all" else [args.theme]):
            r = Renderer(theme, mobile, font, bold, w, h, title)
            frame_fn = getattr(r, name.replace("-", "_") + "_frame")
            r.export(name, duration, fps, frame_fn, poster, args.posters_only)
    if not args.posters_only:
        write_manifest()


if __name__ == "__main__":
    main()
