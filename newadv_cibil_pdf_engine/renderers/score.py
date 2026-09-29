"""Score-gauge rendering support.

The reference PDF's score gauge is a semicircular ring of five filled
bands (red -> orange -> light green -> green -> dark green, separated by
thin white strokes) with a short dark needle and hub. The band geometry is
a fixed visual property of the design, not customer data, so it is a
constant here (measured off the reference PDF: ring radii 32.9/54.8pt,
band boundaries at the angles below) - only the needle angle and the
printed number are data-driven.
"""

from __future__ import annotations

import math

from ..models import Score

# Gauge centre inside the 173.2 x 120pt gauge box (reference: 129.1, 201.7
# on the page, panel origin at 42.5, 147.4).
CX, CY = 86.6, 54.3
R_INNER, R_OUTER = 32.9, 54.8
NEEDLE_LENGTH = 44.8

# (start angle, end angle, colour) - degrees, 180 = left (min), 0 = right
# (max).
GAUGE_BANDS = (
    (180.0, 96.2, "#d82f24"),
    (96.2, 69.25, "#f9a824"),
    (69.25, 48.25, "#7cb342"),
    (48.25, 30.2, "#42a046"),
    (30.2, 0.0, "#1d8e3d"),
)


def _point(radius: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return CX + radius * math.cos(a), CY - radius * math.sin(a)


def _band_path(start: float, end: float) -> str:
    """SVG path for the annular sector between ``start`` and ``end``
    (both in degrees, start > end, drawn clockwise on screen).
    """
    x1, y1 = _point(R_OUTER, start)
    x2, y2 = _point(R_OUTER, end)
    x3, y3 = _point(R_INNER, end)
    x4, y4 = _point(R_INNER, start)
    large = 1 if (start - end) > 180 else 0
    return (
        f"M {x1:.2f} {y1:.2f} "
        f"A {R_OUTER} {R_OUTER} 0 {large} 1 {x2:.2f} {y2:.2f} "
        f"L {x3:.2f} {y3:.2f} "
        f"A {R_INNER} {R_INNER} 0 {large} 0 {x4:.2f} {y4:.2f} Z"
    )


def score_gauge_context(score: Score | None) -> dict | None:
    if score is None or score.value is None:
        return None

    angle_deg = 180 - (score.needle_fraction * 180)
    needle_x, needle_y = _point(NEEDLE_LENGTH, angle_deg)

    return {
        "value": score.value,
        "name": score.name,
        "date": score.date,
        "range_min": score.range_min,
        "range_max": score.range_max,
        "bands": [{"path": _band_path(s, e), "color": c} for s, e, c in GAUGE_BANDS],
        "needle_x": round(needle_x, 2),
        "needle_y": round(needle_y, 2),
        "cx": CX,
        "cy": CY,
        "factors": [f.text for f in score.factors if f.text],
    }
