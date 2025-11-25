# windowcad/views.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from .models import (
    Profile,
    ProfileSystem,
    WindowDesign,
    Panel,
    Mullion,
)
from .services import (
    export_window_to_dxf,
    calculate_panel_hardware,
)


# ============================================================
# 1) List of window designs
# ============================================================

class WindowDesignListView(ListView):
    """
    Simple list of all window/door designs.
    """
    model = WindowDesign
    template_name = "windowcad/window_list.html"
    context_object_name = "windows"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related("system", "frame_profile")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs


# ============================================================
# 2) Detail view: drawing + hardware summary
# ============================================================

class WindowDesignDetailView(DetailView):
    """
    Show basic 2D representation (via SVG in template)
    and hardware summary for each panel.
    """
    model = WindowDesign
    template_name = "windowcad/window_detail.html"
    context_object_name = "window"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        window: WindowDesign = self.object

        panels_data: List[Dict[str, Any]] = []
        hardware_summary: List[Dict[str, Any]] = []

        for p in window.panels.all().order_by("id"):
            hw_items = calculate_panel_hardware(p, window)
            panels_data.append(
                {
                    "x": p.x,
                    "y": p.y,
                    "w": p.w,
                    "h": p.h,
                    "type": p.type,
                    "operation": p.operation,
                }
            )
            hardware_summary.append(
                {
                    "panel": p,
                    "hardware": hw_items,
                }
            )

        ctx["panels_json"] = panels_data
        ctx["hardware_summary"] = hardware_summary
        return ctx


# ============================================================
# 3) Sketch view: draw outer frame + mullions with the mouse
# ============================================================

class WindowSketchView(View):
    """
    Let the user draw the outer rectangle manually (free sketch)
    plus mullions (vertical/horizontal) on an SVG canvas.
    Then create a WindowDesign + default Panel + Mullions.
    """

    template_name = "windowcad/window_sketch.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        systems = ProfileSystem.objects.all().order_by("code")
        frame_profiles = (
            Profile.objects.filter(type="frame")
            .select_related("system")
            .order_by("system__code", "code")
        )
        return render(
            request,
            self.template_name,
            {
                "systems": systems,
                "frame_profiles": frame_profiles,
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        """
        Expected POST fields (sent from JS):

        - name
        - system_id
        - frame_profile_id
        - width_mm
        - height_mm
        - mullions_json  (JSON array: [{orientation, ratio}, ...])
        """
        name = request.POST.get("name") or "Sketch Window"
        system_id = request.POST.get("system_id")
        frame_profile_id = request.POST.get("frame_profile_id")
        width_mm = request.POST.get("width_mm")
        height_mm = request.POST.get("height_mm")
        mullions_json = request.POST.get("mullions_json", "[]")

        # Basic validation
        if not (system_id and frame_profile_id and width_mm and height_mm):
            messages.error(request, "Missing data from sketch.")
            return redirect("windowcad:window_sketch")

        try:
            width_val = float(width_mm)
            height_val = float(height_mm)
        except (TypeError, ValueError):
            messages.error(request, "Invalid dimensions from sketch.")
            return redirect("windowcad:window_sketch")

        if width_val <= 0 or height_val <= 0:
            messages.error(request, "Width/height must be positive.")
            return redirect("windowcad:window_sketch")

        system = get_object_or_404(ProfileSystem, pk=system_id)
        frame_profile = get_object_or_404(Profile, pk=frame_profile_id)

        # Create window design from sketch
        window = WindowDesign.objects.create(
            name=name,
            system=system,
            frame_profile=frame_profile,
            width_mm=width_val,
            height_mm=height_val,
        )

        # For now: a single full panel (0–1)
        Panel.objects.create(
            window=window,
            x=0.0,
            y=0.0,
            w=1.0,
            h=1.0,
            type=Panel.PanelType.FIXED,
            operation=Panel.PanelOperation.FIXED,
        )

        # Parse mullions from JSON and create them
        try:
            data = json.loads(mullions_json or "[]")
        except ValueError:
            data = []

        for item in data:
            orientation = item.get("orientation")
            ratio = item.get("ratio")

            try:
                ratio_val = float(ratio)
            except (TypeError, ValueError):
                continue

            if orientation not in (
                Mullion.Orientation.VERTICAL,
                Mullion.Orientation.HORIZONTAL,
            ):
                continue

            # Clamp ratio to 0–1
            if ratio_val < 0:
                ratio_val = 0.0
            if ratio_val > 1:
                ratio_val = 1.0

            Mullion.objects.create(
                window=window,
                orientation=orientation,
                position_ratio=ratio_val,
                profile=None,  # optional: later we can map to specific mullion profiles
            )

        messages.success(request, "Window design created from sketch.")
        return redirect("windowcad:window_detail", pk=window.pk)


# ============================================================
# 4) DXF download
# ============================================================

def download_window_dxf(request: HttpRequest, pk: int) -> FileResponse:
    """
    Export a DXF file for the given window design using the CAD service.
    """
    window = get_object_or_404(WindowDesign, pk=pk)

    # You can change this path later if you like
    tmp_path = Path("/tmp") / f"window_{window.pk}.dxf"
    export_window_to_dxf(window, tmp_path)

    return FileResponse(
        open(tmp_path, "rb"),
        as_attachment=True,
        filename=tmp_path.name,
    )
