from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Opportunity(models.Model):
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "الفرصة"
        verbose_name_plural = "الفرص"

    def __str__(self) -> str:
        return self.name


class Committee(models.Model):
    name = models.CharField(max_length=200)
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="committees")
    is_open = models.BooleanField(default=True)

    class Meta:
        verbose_name = "اللجنة"
        verbose_name_plural = "اللجان"

    def __str__(self) -> str:
        return f"{self.name} — {self.opportunity}"


class Candidate(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.PROTECT, related_name="candidates")

    full_name = models.CharField(max_length=200)
    national_id = models.CharField(max_length=20, db_index=True)

    start_date = models.DateField(null=True, blank=True)  # تاريخ المباشرة
    rank = models.CharField(max_length=120, blank=True)   # الرتبة
    school = models.CharField(max_length=200, blank=True)
    sector = models.CharField(max_length=200, blank=True)

    file_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
    )
    file_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="file_reviews",
    )
    file_scored_at = models.DateTimeField(null=True, blank=True)

    is_finalized = models.BooleanField(default=False)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="finalizations",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "مرشح"
        verbose_name_plural = "المرشحون"
        unique_together = [("opportunity", "national_id")]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.national_id})"

    def interview_avg(self, committee: Committee) -> float:
        qs = self.interview_scores.filter(committee=committee).values_list("score", flat=True)
        scores = list(qs)
        if len(scores) != 3:
            return 0.0
        total = sum(Decimal(s) for s in scores)
        return float(total / Decimal("3"))

    def final_score(self, committee: Committee) -> float:
        if self.file_score is None:
            return 0.0
        return float(Decimal(self.file_score) + Decimal(str(self.interview_avg(committee))))


class InterviewScore(models.Model):
    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="scores")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="interview_scores")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="interview_scores")

    score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "درجة مقابلة"
        verbose_name_plural = "درجات المقابلات"
        unique_together = [("committee", "candidate", "member")]

    def __str__(self) -> str:
        return f"{self.candidate} | {self.member} | {self.score}"
