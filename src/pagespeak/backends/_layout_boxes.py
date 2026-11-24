"""Layout backend: boxes in PDF page space — union, nearness, containment and overlap."""

from __future__ import annotations

from typing import Any

Box = list[float]
Line = dict[str, Any]


def union(a: Box, b: Box) -> Box:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def near(a: Box, b: Box, gap: float) -> bool:
    return a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]


def mid(ln: Line) -> tuple[float, float]:
    return (ln["x0"] + ln["x1"]) / 2, (ln["y0"] + ln["y1"]) / 2


def inside(ln: Line, box: Box, pad: float = 1) -> bool:
    cx, cy = mid(ln)
    return box[0] - pad <= cx <= box[2] + pad and box[1] - pad <= cy <= box[3] + pad


def overlap(r: Box, f: Box) -> float:
    return max(0, min(r[2], f[2]) - max(r[0], f[0])) * max(0, min(r[3], f[3]) - max(r[1], f[1]))
