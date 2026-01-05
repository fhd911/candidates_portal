from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Candidate, Committee, InterviewScore


# ======================================================
# Helpers (Groups)
# ======================================================
def is_file_reviewer(user) -> bool:
    return user.is_authenticated and user.groups.filter(name="FileReviewers").exists()


def is_interviewer(user) -> bool:
    return user.is_authenticated and user.groups.filter(name="Interviewers").exists()


def is_admin(user) -> bool:
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name="Admins").exists())


def _to_decimal_0_50(value: str | None) -> Decimal | None:
    """Parse score safely; return None if invalid/out of range."""
    if value is None or value == "":
        return None
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if d < 0 or d > 50:
        return None
    return d


# ======================================================
# Dashboard
# ======================================================
@login_required
def dashboard(request):
    return render(request, "candidates/dashboard.html")


# ======================================================
# File Reviewer
# ======================================================
@login_required
@user_passes_test(is_file_reviewer)
def file_review_list(request):
    qs = Candidate.objects.select_related("opportunity").order_by("full_name")
    return render(request, "candidates/file_review_list.html", {"candidates": qs})


@login_required
@user_passes_test(is_file_reviewer)
def file_review_detail(request, pk: int):
    candidate = get_object_or_404(Candidate.objects.select_related("opportunity"), pk=pk)

    if request.method == "POST":
        if candidate.is_finalized:
            messages.warning(request, "النتيجة معتمدة (مقفلة) ولا يمكن تعديل درجة الملف.")
            return redirect("candidates:file_review_list")

        score = _to_decimal_0_50(request.POST.get("file_score"))
        if score is None:
            messages.error(request, "أدخل درجة صحيحة بين 0 و 50.")
            return redirect("candidates:file_review_detail", pk=candidate.pk)

        candidate.file_score = score
        candidate.file_reviewer = request.user
        candidate.file_scored_at = timezone.now()
        candidate.save(update_fields=["file_score", "file_reviewer", "file_scored_at"])

        messages.success(request, "تم حفظ درجة الملف.")
        return redirect("candidates:file_review_list")

    return render(request, "candidates/file_review_detail.html", {"candidate": candidate})


# ======================================================
# Interviewer
# ======================================================
@login_required
@user_passes_test(is_interviewer)
def interview_list(request):
    committees = Committee.objects.select_related("opportunity").filter(is_open=True).order_by("-id")
    candidates = Candidate.objects.select_related("opportunity").order_by("full_name")
    return render(
        request,
        "candidates/interview_list.html",
        {"committees": committees, "candidates": candidates},
    )


@login_required
@user_passes_test(is_interviewer)
def interview_score(request, candidate_id: int, committee_id: int):
    candidate = get_object_or_404(Candidate.objects.select_related("opportunity"), pk=candidate_id)
    committee = get_object_or_404(Committee.objects.select_related("opportunity"), pk=committee_id)

    # ✅ حماية: لا يمكن تقييم مرشح خارج نفس الفرصة
    if candidate.opportunity_id != committee.opportunity_id:
        messages.error(request, "لا يمكن تقييم هذا المرشح ضمن هذه اللجنة (اختلاف الفرصة).")
        return redirect("candidates:interview_list")

    score_obj, _ = InterviewScore.objects.get_or_create(
        candidate=candidate,
        committee=committee,
        member=request.user,
        defaults={"score": Decimal("0.00")},
    )

    if request.method == "POST":
        if candidate.is_finalized:
            messages.warning(request, "النتيجة معتمدة (مقفلة) ولا يمكن تعديل درجة المقابلة.")
            return redirect("candidates:interview_list")

        score = _to_decimal_0_50(request.POST.get("score"))
        if score is None:
            messages.error(request, "أدخل درجة صحيحة بين 0 و 50.")
            return redirect("candidates:interview_score", candidate_id=candidate.pk, committee_id=committee.pk)

        notes = (request.POST.get("notes") or "").strip()
        score_obj.score = score
        score_obj.notes = notes
        score_obj.save(update_fields=["score", "notes"])

        messages.success(request, "تم حفظ درجتك للمقابلة.")
        return redirect("candidates:interview_list")

    return render(
        request,
        "candidates/interview_score.html",
        {"candidate": candidate, "committee": committee, "score_obj": score_obj},
    )


# ======================================================
# Admin Panel
# ======================================================
@login_required
@user_passes_test(is_admin)
def admin_panel(request):
    """
    يعرض المرشحين + اكتمال المقابلة + حساب متوسط المقابلة والنهائي.
    ملاحظة: الاعتماد النهائي سيتم عبر finalize_candidate_auto أو finalize_candidate.
    """
    committees = Committee.objects.select_related("opportunity").all().order_by("-is_open", "-id")

    # نسمح بتحديد لجنة لعرض المقابلات بدقة (مهم للحساب)
    committee_id = request.GET.get("committee")
    active_committee = None
    if committee_id and committee_id.isdigit():
        active_committee = Committee.objects.select_related("opportunity").filter(pk=int(committee_id)).first()

    qs = Candidate.objects.select_related("opportunity").order_by("-is_finalized", "full_name")

    # عدّ المقابلات (إما للجنة محددة أو أي لجنة لنفس الفرصة)
    if active_committee:
        qs = qs.annotate(
            interviews_count=Count(
                "interview_scores",
                filter=Q(interview_scores__committee=active_committee),
            )
        )
    else:
        qs = qs.annotate(interviews_count=Count("interview_scores"))

    # حساب المتوسط/النهائي داخل القالب عبر helpers بسيطة (نمرر committee لو موجود)
    return render(
        request,
        "candidates/admin_panel.html",
        {
            "candidates": qs,
            "committees": committees,
            "active_committee": active_committee,
        },
    )


@login_required
@user_passes_test(is_admin)
def finalize_candidate_auto(request, pk: int):
    """
    اعتماد تلقائي: يختار لجنة مرتبطة بفرصة المرشح (الأحدث/المفتوحة أولاً).
    """
    candidate = get_object_or_404(Candidate.objects.select_related("opportunity"), pk=pk)

    committee = (
        Committee.objects
        .filter(opportunity=candidate.opportunity)
        .order_by("-is_open", "-id")
        .first()
    )
    if not committee:
        messages.error(request, "لا توجد لجنة مرتبطة بهذه الفرصة لاعتماد النتيجة.")
        return redirect("candidates:admin_panel")

    return _finalize(candidate=candidate, committee=committee, request=request)


@login_required
@user_passes_test(is_admin)
def finalize_candidate(request, pk: int, committee_id: int):
    """
    اعتماد يدوي: يعتمد المرشح بناءً على لجنة محددة.
    """
    candidate = get_object_or_404(Candidate.objects.select_related("opportunity"), pk=pk)
    committee = get_object_or_404(Committee.objects.select_related("opportunity"), pk=committee_id)
    return _finalize(candidate=candidate, committee=committee, request=request)


def _finalize(*, candidate: Candidate, committee: Committee, request):
    # حماية: نفس الفرصة
    if candidate.opportunity_id != committee.opportunity_id:
        messages.error(request, "لا يمكن اعتماد النتيجة (اختلاف الفرصة بين المرشح واللجنة).")
        return redirect("candidates:admin_panel")

    if candidate.is_finalized:
        messages.info(request, "النتيجة معتمدة مسبقًا.")
        return redirect("candidates:admin_panel")

    if candidate.file_score is None:
        messages.error(request, "لا يمكن الاعتماد: درجة الملف غير مدخلة.")
        return redirect("candidates:admin_panel")

    cnt = candidate.interview_scores.filter(committee=committee).count()
    if cnt != 3:
        messages.error(request, f"لا يمكن الاعتماد: المقابلة غير مكتملة (الموجود {cnt}/3).")
        return redirect("candidates:admin_panel")

    candidate.is_finalized = True
    candidate.finalized_by = request.user
    candidate.finalized_at = timezone.now()
    candidate.save(update_fields=["is_finalized", "finalized_by", "finalized_at"])

    messages.success(request, "تم اعتماد النتيجة بنجاح.")
    return redirect("candidates:admin_panel")
