# contacts/urls.py
from django.urls import path
from . import views

app_name = "contacts"

urlpatterns = [
    path(
        "",
        views.ContactListView.as_view(),
        name="contact_list",
    ),
    path(
        "new/",
        views.ContactCreateView.as_view(),
        name="contact_create",
    ),
    path(
        "<int:pk>/",
        views.ContactDetailView.as_view(),
        name="contact_detail",
    ),
    path(
        "<int:pk>/edit/",
        views.ContactUpdateView.as_view(),
        name="contact_edit",
    ),
    path(
        "<int:pk>/delete/",
        views.ContactDeleteView.as_view(),
        name="contact_delete",
    ),
    path(
        "autocomplete/",
        views.ContactAutocompleteView.as_view(),
        name="contact_autocomplete",
    ),
]
