from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


# ==========================================================
# Core
# ==========================================================

class Opportunity(models.Model):
    """
    تمثل "الفرصة" أو "حركة/منافسة" مستقلة.
    مثال: حركة وكلاء 1447، مدير مدرسة، ...إلخ
    """
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "الفرصة"
        verbose_name_plural = "الفرص"

    def __str__(self) -> str:
        return self.name


class Committee(models.Model):
    """
    اللجنة مرتبطة بفرصة.
    كل لجنة لها 3 أعضاء (رئيس + عضوين) عبر MemberProfile.
    """
    name = models.CharField(max_length=200)
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="committees",
    )
    is_open = models.BooleanField(default=True)

    class Meta:
        verbose_name = "اللجنة"
        verbose_name_plural = "اللجان"
        unique_together = [("opportunity", "name")]
        indexes = [models.Index(fields=["opportunity", "name"])]

    def __str__(self) -> str:
        return f"{self.name} — {self.opportunity}"


# ==========================================================
# Member Profile (Login by national id + last4)
# ==========================================================

class MemberProfile(models.Model):
    """
    يربط المستخدم (User) بالسجل المدني + آخر 4 أرقام من الجوال + الدور + (اللجنة/الفرصة).
    هذا هو الأساس للدخول بدون كلمات مرور.
    """

    ROLE_SUPERVISOR = "supervisor"
    ROLE_MEMBER = "member"
    ROLE_CHAIR = "chair"
    ROLE_ADMIN = "admin"

    ROLE_CHOICES = [
        (ROLE_SUPERVISOR, "مشرف ملف"),
        (ROLE_MEMBER, "عضو لجنة"),
        (ROLE_CHAIR, "رئيس لجنة"),
        (ROLE_ADMIN, "إدارة"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="المستخدم",
    )

    national_id = models.CharField("السجل المدني", max_length=20, db_index=True)
    mobile_last4 = models.CharField("آخر 4 من الجوال", max_length=4)

    role = models.CharField("الدور", max_length=20, choices=ROLE_CHOICES)

    # للمشرف/الإدارة: ربط بفرصة محددة (اختياري لكنه عملي)
    opportunity = models.ForeignKey(
        Opportunity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_profiles",
        verbose_name="الفرصة",
    )

    # للأعضاء/الرئيس: ربط باللجنة
    committee = models.ForeignKey(
        Committee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_profiles",
        verbose_name="اللجنة",
    )

    is_active = models.BooleanField("مفعّل", default=True)

    class Meta:
        verbose_name = "ملف مستخدم"
        verbose_name_plural = "ملفات المستخدمين"
        indexes = [
            models.Index(fields=["national_id", "mobile_last4"]),
            models.Index(fields=["role"]),
        ]
        constraints = [
            # العضو/الرئيس لابد يكون مربوط بلجنة
            models.CheckConstraint(
                name="memberprofile_committee_required_for_committee_roles",
                condition=(~Q(role__in=["member", "chair"]) | Q(committee__isnull=False)),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()}"


# ==========================================================
# Candidate
# ==========================================================

class Candidate(models.Model):
    """
    المرشح داخل فرصة محددة.
    - يدخل المشرف ويسجل file_score أو file_not_eligible + reason
    - بعدها يتم توزيع المرشح على لجنة واحدة assigned_committee
    - اللجنة تسجل 3 درجات InterviewScore
    - رئيس اللجنة يعتمد FinalDecision ويقفل
    """

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name="candidates",
    )

    assigned_committee = models.ForeignKey(
        Committee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_candidates",
        verbose_name="اللجنة المعيّنة",
    )

    full_name = models.CharField("اسم المتقدم", max_length=200)
    national_id = models.CharField("السجل المدني", max_length=20, db_index=True)
    mobile = models.CharField("رقم الجوال", max_length=20, blank=True, default="")

    # ---- Excel fields ----
    specialization = models.CharField("التخصص", max_length=200, blank=True, default="")
    rank = models.CharField("الرتبة الوظيفية", max_length=120, blank=True, default="")
    current_work = models.CharField("العمل الحالي", max_length=200, blank=True, default="")
    start_date_hijri = models.CharField("تاريخ المباشرة (هجري)", max_length=40, blank=True, default="")

    school = models.CharField("مدرسة المتقدم", max_length=200, blank=True, default="")
    sector = models.CharField("قطاع المتقدم", max_length=200, blank=True, default="")

    applied_position = models.CharField("الوظيفة المتقدم عليها", max_length=200, blank=True, default="")
    opportunity_school = models.CharField("مدرسة الفرصة", max_length=200, blank=True, default="")
    opportunity_sector = models.CharField("قطاع الفرصة", max_length=200, blank=True, default="")

    admin_exp = models.CharField("سبق العمل في الإدارة المدرسية", max_length=40, blank=True, default="")
    years_director = models.PositiveIntegerField("سنوات عمل مدير", default=0)
    years_deputy = models.PositiveIntegerField("سنوات عمل وكيل", default=0)
    cv_url = models.URLField("رابط السيرة الذاتية", blank=True, default="")

    # ======================================================
    # File evaluation (Supervisor)
    # ======================================================

    file_score = models.DecimalField(
        "درجة الملف (0-50)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
    )

    file_not_eligible = models.BooleanField("لا يرشح (ملف)", default=False)
    file_not_eligible_reason = models.CharField("سبب عدم الترشيح (ملف)", max_length=250, blank=True, default="")

    file_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="file_reviews",
        verbose_name="مقيّم الملف (مشرف)",
    )
    file_scored_at = models.DateTimeField("وقت تقييم الملف", null=True, blank=True)

    # ======================================================
    # Final decision (Chair)
    # ======================================================

    is_finalized = models.BooleanField("مقفل/معتمد نهائيًا", default=False)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="finalizations",
        verbose_name="اعتماد رئيس اللجنة",
    )
    finalized_at = models.DateTimeField("وقت الاعتماد", null=True, blank=True)

    class Meta:
        verbose_name = "مرشح"
        verbose_name_plural = "المرشحون"
        unique_together = [("opportunity", "national_id")]
        indexes = [
            models.Index(fields=["opportunity", "national_id"]),
            models.Index(fields=["opportunity", "assigned_committee"]),
            models.Index(fields=["opportunity", "is_finalized"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.national_id})"

    def interview_scores_for_committee(self, committee: Committee):
        return self.interview_scores.filter(committee=committee).values_list("score", flat=True)

    def interview_avg(self, committee: Committee) -> float:
        scores = list(self.interview_scores_for_committee(committee))
        if len(scores) != 3:
            return 0.0
        total = sum(Decimal(s) for s in scores)
        return float(total / Decimal("3"))

    def final_score(self, committee: Committee) -> float:
        if self.file_not_eligible:
            return 0.0
        if self.file_score is None:
            return 0.0
        return float(Decimal(self.file_score) + Decimal(str(self.interview_avg(committee))))

    @property
    def is_ready_for_distribution(self) -> bool:
        return (self.file_score is not None) or self.file_not_eligible

    @property
    def is_assigned(self) -> bool:
        return self.assigned_committee_id is not None


# ==========================================================
# Interview scores
# ==========================================================

class InterviewScore(models.Model):
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="scores",
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="interview_scores",
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="interview_scores",
    )

    score = models.DecimalField(
        "درجة المقابلة (0-50)",
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
    )
    notes = models.TextField("ملاحظات", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "درجة مقابلة"
        verbose_name_plural = "درجات المقابلات"
        unique_together = [("committee", "candidate", "member")]
        indexes = [
            models.Index(fields=["committee", "candidate"]),
            models.Index(fields=["member"]),
        ]

    def __str__(self) -> str:
        return f"{self.candidate} | {self.member} | {self.score}"


# ==========================================================
# Final Decision
# ==========================================================

class FinalDecision(models.Model):
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="final_decisions",
    )
    candidate = models.OneToOneField(
        Candidate,
        on_delete=models.CASCADE,
        related_name="final_decision",
    )

    is_nominated = models.BooleanField("يرشح للمقابلة/المرحلة التالية", default=False)
    reason = models.CharField("سبب عدم الترشيح (إن وجد)", max_length=250, blank=True, default="")

    final_score_value = models.DecimalField(
        "الدرجة النهائية (محسوبة)",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_decisions",
        verbose_name="رئيس اللجنة",
    )
    submitted_at = models.DateTimeField("وقت الإرسال", auto_now_add=True)

    class Meta:
        verbose_name = "قرار نهائي"
        verbose_name_plural = "القرارات النهائية"
        unique_together = [("committee", "candidate")]
        indexes = [models.Index(fields=["committee", "is_nominated"])]

    def __str__(self) -> str:
        return f"{self.candidate} — {self.committee} — {'يرشح' if self.is_nominated else 'لا يرشح'}"
