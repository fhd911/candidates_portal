from django.contrib import admin
from .models import Opportunity, Committee, Candidate, InterviewScore


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "opportunity", "is_open")
    list_filter = ("is_open", "opportunity")
    search_fields = ("name",)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "national_id",
        "opportunity",
        "sector",
        "school",
        "file_score",
        "is_finalized",
    )
    list_filter = ("opportunity", "sector", "is_finalized")
    search_fields = ("full_name", "national_id", "school", "sector")


@admin.register(InterviewScore)
class InterviewScoreAdmin(admin.ModelAdmin):
    list_display = ("id", "committee", "candidate", "member", "score", "created_at")
    list_filter = ("committee", "member")
    search_fields = ("candidate__full_name", "candidate__national_id", "member__username")
