# windowcad/models.py
from django.db import models
from django.utils.translation import gettext_lazy as _


class ProfileSystem(models.Model):
    """
    Aluminum system (e.g., MZN-46, Thermal-60, etc.).
    Represents a family of profiles.
    """
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text=_("Short code of the system, e.g. MZN-46."),
    )
    name = models.CharField(
        max_length=200,
        help_text=_("Full name/description of the system."),
    )

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"


class Profile(models.Model):
    """
    Single profile inside a system: frame, sash, mullion, transom...
    """

    class ProfileType(models.TextChoices):
        FRAME = "frame", _("Outer Frame")
        SASH = "sash", _("Sash / Leaf")
        MULLION = "mullion", _("Mullion")
        TRANSOM = "transom", _("Transom")

    system = models.ForeignKey(
        ProfileSystem,
        on_delete=models.CASCADE,
        related_name="profiles",
        help_text=_("Parent aluminum system."),
    )

    code = models.CharField(
        max_length=50,
        help_text=_("Profile code inside the system."),
    )

    type = models.CharField(
        max_length=20,
        choices=ProfileType.choices,
        help_text=_("Profile usage type (frame, sash, mullion, ...)."),
    )

    # Simplified 2D visible width and total depth
    visible_width_mm = models.FloatField(
        help_text=_("Visible face width of profile in 2D (mm)."),
    )
    depth_mm = models.FloatField(
        help_text=_("Profile depth (mm)."),
    )

    class Meta:
        unique_together = ("system", "code")

    def __str__(self) -> str:
        return f"{self.system.code} – {self.code} ({self.get_type_display()})"


class WindowDesign(models.Model):
    """
    Main window/door design created either from sketch or forms.
    Panels, mullions, hardware calculations, etc. hang from here.
    """

    name = models.CharField(
        max_length=200,
        help_text=_("Name of the window/door design (e.g. Living room window)."),
    )

    # Overall opening (building size) in mm
    width_mm = models.FloatField(
        help_text=_("Total opening width (mm)."),
    )
    height_mm = models.FloatField(
        help_text=_("Total opening height (mm)."),
    )

    system = models.ForeignKey(
        ProfileSystem,
        on_delete=models.PROTECT,
        related_name="windows",
        help_text=_("Aluminum system used for this design."),
    )

    frame_profile = models.ForeignKey(
        Profile,
        on_delete=models.PROTECT,
        related_name="frame_windows",
        limit_choices_to={"type": "frame"},
        help_text=_("Outer frame profile used for perimeter."),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self) -> str:
        return self.name

    @property
    def frame_face_mm(self) -> float:
        """
        Visible face width of the frame profile (used as offset in 2D).
        """
        return self.frame_profile.visible_width_mm


class Panel(models.Model):
    """
    Single panel (leaf / fixed glass / door) inside a window.
    Coordinates are stored as ratios (0–1) relative to the *clear opening*
    (inside the frame).
    """

    class PanelType(models.TextChoices):
        FIXED = "fixed", _("Fixed Glass")
        WINDOW = "window", _("Window Leaf")
        DOOR = "door", _("Door Leaf")

    class PanelOperation(models.TextChoices):
        FIXED = "fixed", _("Fixed")
        TURN = "turn", _("Turn (Side Hung)")
        TILT_TURN = "tilt_turn", _("Tilt & Turn")
        TILT = "tilt", _("Tilt Only")
        DOOR = "door", _("Hinged Door")
        SLIDING = "sliding", _("Sliding")

    window = models.ForeignKey(
        WindowDesign,
        on_delete=models.CASCADE,
        related_name="panels",
    )

    # Ratios relative to clear opening (0–1)
    x = models.FloatField(
        help_text=_("Left ratio (0–1) in clear opening."),
    )
    y = models.FloatField(
        help_text=_("Top ratio (0–1) in clear opening."),
    )
    w = models.FloatField(
        help_text=_("Width ratio (0–1) in clear opening."),
    )
    h = models.FloatField(
        help_text=_("Height ratio (0–1) in clear opening."),
    )

    type = models.CharField(
        max_length=20,
        choices=PanelType.choices,
        default=PanelType.FIXED,
        help_text=_("Panel type (fixed, window leaf, door leaf)."),
    )

    operation = models.CharField(
        max_length=20,
        choices=PanelOperation.choices,
        default=PanelOperation.FIXED,
        help_text=_("Operation type (turn, tilt-turn, door, sliding, ...)."),
    )

    def __str__(self) -> str:
        return f"{self.window.name} – {self.get_type_display()} ({self.x:.2f},{self.y:.2f})"


class Mullion(models.Model):
    """
    Simple mullion definition inside the clear opening.
    Stored as a ratio 0–1 across the clear width/height.
    """

    class Orientation(models.TextChoices):
        VERTICAL = "vertical", _("Vertical")
        HORIZONTAL = "horizontal", _("Horizontal")

    window = models.ForeignKey(
        WindowDesign,
        on_delete=models.CASCADE,
        related_name="mullions",
    )

    orientation = models.CharField(
        max_length=10,
        choices=Orientation.choices,
        help_text=_("Vertical or horizontal mullion."),
    )

    position_ratio = models.FloatField(
        help_text=_("Position between 0–1 across the clear opening."),
    )

    profile = models.ForeignKey(
        Profile,
        on_delete=models.PROTECT,
        related_name="mullion_windows",
        null=True,
        blank=True,
        limit_choices_to={"type": "mullion"},
        help_text=_("Optional specific mullion profile."),
    )

    @property
    def visible_face_mm(self) -> float:
        """
        Visible thickness of this mullion in 2D.
        If a mullion profile is set, use its visible_width_mm.
        Otherwise, fall back to the window frame face.
        """
        if self.profile:
            return self.profile.visible_width_mm
        return self.window.frame_face_mm

    def __str__(self) -> str:
        return f"{self.window.name} – {self.get_orientation_display()} @ {self.position_ratio:.2f}"



class HardwareItem(models.Model):
    """
    Simplified hardware item linked to a panel operation type.
    In real life this would be much richer (weight, series, brand, etc.).
    """

    code = models.CharField(
        max_length=50,
        help_text=_("Hardware code / reference."),
    )
    name = models.CharField(
        max_length=255,
        help_text=_("Hardware description."),
    )

    # Which type of operation this hardware belongs to
    for_operation = models.CharField(
        max_length=20,
        choices=Panel.PanelOperation.choices,
        help_text=_("Operation type this hardware is valid for."),
    )

    # Size limits where this hardware is valid
    min_height_mm = models.FloatField(
        default=0,
        help_text=_("Minimum panel height (mm) for this hardware."),
    )
    max_height_mm = models.FloatField(
        default=10000,
        help_text=_("Maximum panel height (mm) for this hardware."),
    )
    min_width_mm = models.FloatField(
        default=0,
        help_text=_("Minimum panel width (mm) for this hardware."),
    )
    max_width_mm = models.FloatField(
        default=10000,
        help_text=_("Maximum panel width (mm) for this hardware."),
    )

    # Base quantity per panel (can later be scaled)
    quantity_per_panel = models.FloatField(
        default=1.0,
        help_text=_("Base quantity per panel (before scaling by size)."),
    )

    depends_on_height = models.BooleanField(
        default=False,
        help_text=_("If true, quantity scales with panel height."),
    )
    depends_on_width = models.BooleanField(
        default=False,
        help_text=_("If true, quantity scales with panel width."),
    )

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"
