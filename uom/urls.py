# uom/urls.py
from django.urls import path

from .views import (
    UnitOfMeasureListView,
    UnitOfMeasureCreateView,
    UnitOfMeasureUpdateView,
)

app_name = "uom"

urlpatterns = [
    path("units/", UnitOfMeasureListView.as_view(), name="unit_list"),
    path("units/new/", UnitOfMeasureCreateView.as_view(), name="unit_create"),
    path("units/<int:pk>/edit/", UnitOfMeasureUpdateView.as_view(), name="unit_update"),
]
