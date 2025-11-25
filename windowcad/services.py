# windowcad/services.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import ezdxf

from .models import (
    WindowDesign,
    Panel,
    Mullion,
    HardwareItem,
)


# ============================================================
# Geometry helpers
# ============================================================

def get_clear_opening(window: WindowDesign) -> tuple[float, float, float, float]:
    """
    Returns (x0, y0, width, height) of the clear opening (inside the frame).

    x0, y0  : top-left corner of clear opening (mm)
    width   : clear width (mm)
    height  : clear height (mm)
    """
    frame = window.frame_face_mm
    total_w = window.width_mm
    total_h = window.height_mm

    clear_w = total_w - 2 * frame
    clear_h = total_h - 2 * frame

    return frame, frame, clear_w, clear_h


# ============================================================
# DXF export (2D mini-CAD)
# ============================================================

def export_window_to_dxf(window: WindowDesign, output_path: Path) -> Path:
    """
    Create a simple 2D DXF with:
    - outer frame (building opening)
    - inner frame (frame profile)
    - mitered corners at 45°
    - panels (colored by type)
    - mullions (as rectangular bars with own visible thickness)
    """
    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()

    total_w = window.width_mm
    total_h = window.height_mm
    frame = window.frame_face_mm

    # 1) Outer opening (0,0)-(W,H)
    msp.add_lwpolyline(
        [(0, 0), (total_w, 0), (total_w, total_h), (0, total_h), (0, 0)],
        close=True,
        dxfattribs={"color": 7},  # white/black
    )

    # 1.1) Miter 45° at outer corners using frame thickness
    t = frame

    # top-left
    msp.add_line(
        (0, t),
        (t, 0),
        dxfattribs={"color": 7},
    )
    # top-right
    msp.add_line(
        (total_w - t, 0),
        (total_w, t),
        dxfattribs={"color": 7},
    )
    # bottom-right
    msp.add_line(
        (total_w, total_h - t),
        (total_w - t, total_h),
        dxfattribs={"color": 7},
    )
    # bottom-left
    msp.add_line(
        (t, total_h),
        (0, total_h - t),
        dxfattribs={"color": 7},
    )

    # 2) Inner frame (offset by frame face)
    msp.add_lwpolyline(
        [
            (frame, frame),
            (total_w - frame, frame),
            (total_w - frame, total_h - frame),
            (frame, total_h - frame),
            (frame, frame),
        ],
        close=True,
        dxfattribs={"color": 2},  # yellow/green
    )

    # 3) Panels (inside clear opening)
    x0, y0, clear_w, clear_h = get_clear_opening(window)

    for p in window.panels.all():
        px = x0 + p.x * clear_w
        py = y0 + p.y * clear_h
        pw = p.w * clear_w
        ph = p.h * clear_h

        color = 4  # default: blue-ish
        if p.type == Panel.PanelType.DOOR:
            color = 1  # red
        elif p.type == Panel.PanelType.WINDOW:
            color = 5  # magenta
        elif p.type == Panel.PanelType.FIXED:
            color = 3  # green

        msp.add_lwpolyline(
            [(px, py), (px + pw, py), (px + pw, py + ph), (px, py + ph), (px, py)],
            close=True,
            dxfattribs={"color": color},
        )

    # 4) Mullions as simple rectangular bars using their visible thickness
    for m in window.mullions.all():
        thickness = m.visible_face_mm  # من البروفايل إن وجد، أو يرجع للفريم

        if m.orientation == Mullion.Orientation.VERTICAL:
            # vertical mullion across the clear opening
            center_x = x0 + m.position_ratio * clear_w
            left = center_x - thickness / 2.0
            right = center_x + thickness / 2.0

            msp.add_lwpolyline(
                [
                    (left, y0),
                    (right, y0),
                    (right, y0 + clear_h),
                    (left, y0 + clear_h),
                    (left, y0),
                ],
                close=True,
                dxfattribs={"color": 6},  # cyan
            )

        elif m.orientation == Mullion.Orientation.HORIZONTAL:
            # horizontal mullion across the clear opening
            center_y = y0 + m.position_ratio * clear_h
            top = center_y - thickness / 2.0
            bottom = center_y + thickness / 2.0

            msp.add_lwpolyline(
                [
                    (x0, top),
                    (x0 + clear_w, top),
                    (x0 + clear_w, bottom),
                    (x0, bottom),
                    (x0, top),
                ],
                close=True,
                dxfattribs={"color": 6},  # cyan
            )

    # Ensure folder exists and save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output_path)
    return output_path


# ============================================================
# Hardware calculation
# ============================================================

def calculate_panel_hardware(panel: Panel, window: WindowDesign) -> List[Dict]:
    """
    Return a list of hardware items (code, name, qty) required for this panel,
    based on its operation type and size and simple rules.
    """
    x0, y0, clear_w, clear_h = get_clear_opening(window)
    panel_width = panel.w * clear_w
    panel_height = panel.h * clear_h

    result: List[Dict] = []

    hardware_qs = HardwareItem.objects.filter(
        for_operation=panel.operation,
        min_height_mm__lte=panel_height,
        max_height_mm__gte=panel_height,
        min_width_mm__lte=panel_width,
        max_width_mm__gte=panel_width,
    )

    for hw in hardware_qs:
        qty = hw.quantity_per_panel

        # Example: scale by height/width if needed
        if hw.depends_on_height:
            # 1 unit per meter of height
            qty *= panel_height / 1000.0

        if hw.depends_on_width:
            # 1 unit per meter of width
            qty *= panel_width / 1000.0

        result.append(
            {
                "code": hw.code,
                "name": hw.name,
                "qty": round(qty, 2),
            }
        )

    return result
