from __future__ import annotations

from django.urls import path
from . import views

app_name = "candidates"

urlpatterns = [
    # Home
    path("", views.home, name="home"),

    # Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # File scoring (Unified) — Supervisor + Chair
    path("file/<int:pk>/", views.file_score_view, name="file_score"),

    # Supervisor
    path("supervisor/", views.supervisor_dashboard, name="supervisor_dashboard"),

    # Admin
    path("dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("distribution/", views.distribution_view, name="distribution"),

    # Committee
    path("committee/", views.committee_dashboard, name="committee_dashboard"),
    path("committee/candidate/<int:pk>/", views.committee_score, name="committee_score"),

    # Chair finalize
    path("committee/final/<int:pk>/", views.chair_finalize, name="chair_finalize"),
]
