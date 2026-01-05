from __future__ import annotations

from django.urls import path
from . import views

app_name = "candidates"

urlpatterns = [
    # =========================
    # Home
    # =========================
    path("", views.dashboard, name="dashboard"),

    # =========================
    # File Reviewer
    # =========================
    path("file-review/", views.file_review_list, name="file_review_list"),
    path("file-review/<int:pk>/", views.file_review_detail, name="file_review_detail"),

    # =========================
    # Interviewer
    # =========================
    path("interview/", views.interview_list, name="interview_list"),
    path(
        "interview/<int:candidate_id>/committee/<int:committee_id>/",
        views.interview_score,
        name="interview_score",
    ),

    # =========================
    # Admin Panel
    # =========================
    path("admin-panel/", views.admin_panel, name="admin_panel"),

    # ✅ اعتماد تلقائي (يختار لجنة المرشح المناسبة تلقائيًا)
    path("finalize/<int:pk>/", views.finalize_candidate_auto, name="finalize_candidate_auto"),

    # (اختياري) اعتماد يدوي لو احتجته لاحقًا
    path(
        "finalize/<int:pk>/committee/<int:committee_id>/",
        views.finalize_candidate,
        name="finalize_candidate",
    ),
]
