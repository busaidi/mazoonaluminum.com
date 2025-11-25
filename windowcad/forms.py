# windowcad/forms.py
from django import forms
from django.forms import inlineformset_factory

from .models import WindowDesign, Panel


class WindowDesignForm(forms.ModelForm):
    class Meta:
        model = WindowDesign
        fields = [
            "name",
            "system",
            "frame_profile",
            "width_mm",
            "height_mm",
        ]


class PanelForm(forms.ModelForm):
    class Meta:
        model = Panel
        fields = [
            "x", "y", "w", "h",
            "type",
            "operation",
        ]


PanelFormSet = inlineformset_factory(
    WindowDesign,
    Panel,
    form=PanelForm,
    extra=1,
    can_delete=True,
)
