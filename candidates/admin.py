from __future__ import annotations

from django.contrib import admin
from django.db.models import Q

from .models import (
    Opportunity,
    Committee,
    MemberProfile,
    Candidate,
    InterviewScore,
    FinalDecision,
)


# ==========================================================
# Opportunity
# ==========================================================

@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("-id",)


# ==========================================================
# Committee
# ==========================================================

@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "opportunity", "is_open")
    list_filter = ("is_open", "opportunity")
    search_fields = ("name", "opportunity__name")
    ordering = ("opportunity", "name")
    list_select_related = ("opportunity",)


# ==========================================================
# MemberProfile (login identity + role)
# ==========================================================

@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "national_id", "mobile_last4", "opportunity", "committee", "is_active")
    list_filter = ("role", "is_active", "opportunity", "committee")
    search_fields = ("user__username", "user__first_name", "user__last_name", "national_id")
    ordering = ("role", "user__username")
    list_select_related = ("user", "opportunity", "committee")

    # منع الأخطاء الشائعة في الإدخال
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["mobile_last4"].help_text = "أدخل آخر 4 أرقام فقط (مثال: 1234)."
        form.base_fields["national_id"].help_text = "السجل المدني بدون مسافات."
        return form


# ==========================================================
# Candidate
# ==========================================================

@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "national_id",
        "opportunity",
        "assigned_committee",
        "sector",
        "school",
        "file_score",
        "file_not_eligible",
        "is_finalized",
    )
    list_filter = ("opportunity", "assigned_committee", "sector", "file_not_eligible", "is_finalized")
    search_fields = ("full_name", "national_id", "school", "sector", "opportunity__name")
    ordering = ("opportunity", "full_name")
    list_select_related = ("opportunity", "assigned_committee")

    readonly_fields = ("file_scored_at", "finalized_at")

    fieldsets = (
        ("بيانات المرشح", {
            "fields": (
                "opportunity",
                "assigned_committee",
                "full_name",
                "national_id",
                "mobile",
            )
        }),
        ("بيانات مستوردة (Excel)", {
            "fields": (
                "specialization",
                "rank",
                "current_work",
                "start_date_hijri",
                "school",
                "sector",
                "applied_position",
                "opportunity_school",
                "opportunity_sector",
                "admin_exp",
                "years_director",
                "years_deputy",
                "cv_url",
            )
        }),
        ("تقييم الملف (المشرف)", {
            "fields": (
                "file_score",
                "file_not_eligible",
                "file_not_eligible_reason",
                "file_reviewer",
                "file_scored_at",
            )
        }),
        ("الإقفال/الاعتماد (رئيس اللجنة)", {
            "fields": (
                "is_finalized",
                "finalized_by",
                "finalized_at",
            )
        }),
    )

    # فلتر سريع "جاهز للتوزيع" (تقييم ملف أو مستبعد)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("opportunity", "assigned_committee", "file_reviewer", "finalized_by")


# ==========================================================
# InterviewScore
# ==========================================================

@admin.register(InterviewScore)
class InterviewScoreAdmin(admin.ModelAdmin):
    list_display = ("id", "committee", "candidate", "member", "score", "created_at")
    list_filter = ("committee", "member")
    search_fields = ("candidate__full_name", "candidate__national_id", "member__username")
    ordering = ("-created_at",)
    list_select_related = ("committee", "candidate", "member")

    readonly_fields = ("created_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("committee", "candidate", "member")


# ==========================================================
# FinalDecision
# ==========================================================

@admin.register(FinalDecision)
class FinalDecisionAdmin(admin.ModelAdmin):
    list_display = ("id", "committee", "candidate", "is_nominated", "final_score_value", "submitted_by", "submitted_at")
    list_filter = ("committee", "is_nominated")
    search_fields = ("candidate__full_name", "candidate__national_id", "submitted_by__username")
    ordering = ("-submitted_at",)
    list_select_related = ("committee", "candidate", "submitted_by")

    readonly_fields = ("submitted_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("committee", "candidate", "submitted_by")
