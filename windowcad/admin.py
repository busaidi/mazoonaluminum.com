# windowcad/admin.py
from django.contrib import admin

from .models import (
    ProfileSystem,
    Profile,
    WindowDesign,
    Panel,
    Mullion,
    HardwareItem,
)

from windowcad.models import Mullion, Panel


# ============================================================
# Profiles inside a system (inline)
# ============================================================

class ProfileInline(admin.TabularInline):
    model = Profile
    extra = 1
    fields = (
        "code",
        "type",
        "visible_width_mm",
        "depth_mm",
    )
    show_change_link = True


@admin.register(ProfileSystem)
class ProfileSystemAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    inlines = [ProfileInline]


# ============================================================
# Panels + Mullions inside a window (inline)
# ============================================================

class PanelInline(admin.TabularInline):
    model = Panel
    extra = 0
    fields = (
        "x",
        "y",
        "w",
        "h",
        "type",
        "operation",
    )
    show_change_link = True


class MullionInline(admin.TabularInline):
    model = Mullion
    extra = 0
    fields = (
        "orientation",
        "position_ratio",
        "profile",
    )
    show_change_link = True


@admin.register(WindowDesign)
class WindowDesignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "system",
        "frame_profile",
        "width_mm",
        "height_mm",
        "created_at",
    )
    list_filter = ("system", "frame_profile")
    search_fields = (
        "name",
        "system__code",
        "system__name",
    )
    readonly_fields = ("created_at",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "system",
                    "frame_profile",
                )
            },
        ),
        (
            "Dimensions (mm)",
            {
                "fields": (
                    "width_mm",
                    "height_mm",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [PanelInline, MullionInline]


# ============================================================
# Profiles admin (full list)
# ============================================================

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "system",
        "type",
        "visible_width_mm",
        "depth_mm",
    )
    list_filter = ("system", "type")
    search_fields = (
        "code",
        "system__code",
        "system__name",
    )
    autocomplete_fields = ("system",)


# ============================================================
# Hardware admin
# ============================================================

@admin.register(HardwareItem)
class HardwareItemAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "for_operation",
        "min_width_mm",
        "max_width_mm",
        "min_height_mm",
        "max_height_mm",
        "quantity_per_panel",
        "depends_on_width",
        "depends_on_height",
    )
    list_filter = (
        "for_operation",
        "depends_on_height",
        "depends_on_width",
    )
    search_fields = ("code", "name")


@admin.register(Mullion)
class PanelAdmin(admin.ModelAdmin):
    pass


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    pass