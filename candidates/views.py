from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Q, Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Candidate, Committee, FinalDecision, InterviewScore, MemberProfile, Opportunity


# ==========================================================
# Helpers
# ==========================================================

def get_profile(request: HttpRequest) -> MemberProfile | None:
    if not request.user.is_authenticated:
        return None
    return getattr(request.user, "profile", None)


def require_role(request: HttpRequest, roles: set[str]) -> MemberProfile | HttpResponse:
    p = get_profile(request)
    if not p or not p.is_active:
        # ✅ مهم: نفصل الجلسة إن كانت موجودة لتجنب حلقات التحويل
        if request.user.is_authenticated:
            logout(request)
        return redirect("candidates:login")
    if p.role not in roles:
        return redirect("candidates:home")
    return p


def get_active_opportunity_for_profile(p: MemberProfile) -> Opportunity | None:
    if getattr(p, "opportunity_id", None):
        return p.opportunity
    return Opportunity.objects.filter(is_active=True).first()


def parse_decimal_0_50(value: str) -> Decimal | None:
    try:
        v = Decimal((value or "").strip())
    except (InvalidOperation, ValueError):
        return None
    if v < 0 or v > 50:
        return None
    return v


def apply_search(qs, q: str):
    """
    بحث خفيف بدون JS.
    إذا لا يوجد national_id في Candidate احذف شرط national_id.
    """
    q = (q or "").strip()
    if not q:
        return qs

    cond = Q(full_name__icontains=q)

    # اختياري إن كان موجوداً لديك في Candidate:
    # cond |= Q(national_id__icontains=q)

    return qs.filter(cond)


# ==========================================================
# Home (Auto Route by Role)
# ==========================================================

def home(request: HttpRequest) -> HttpResponse:
    p = get_profile(request)
    if not p or not getattr(p, "is_active", False):
        if request.user.is_authenticated:
            logout(request)
        return redirect("candidates:login")

    if p.role == MemberProfile.ROLE_SUPERVISOR:
        return redirect("candidates:supervisor_dashboard")
    if p.role in (MemberProfile.ROLE_MEMBER, MemberProfile.ROLE_CHAIR):
        return redirect("candidates:committee_dashboard")
    return redirect("candidates:admin_dashboard")


# ==========================================================
# Auth (NO role selection)  ✅ Fix redirect loop
# ==========================================================

@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    # ✅ منع حلقة التحويل:
    # إذا المستخدم مسجّل دخول لكن بدون Profile أو غير مفعّل → logout ثم عرض login
    if request.user.is_authenticated:
        p = getattr(request.user, "profile", None)
        if p and getattr(p, "is_active", False):
            return redirect("candidates:home")

        logout(request)
        messages.error(request, "حسابك غير مرتبط بملف صلاحيات أو غير مفعّل. راجع الإدارة.")
        return redirect("candidates:login")

    if request.method == "POST":
        national_id = (request.POST.get("national_id") or "").strip()
        last4 = (request.POST.get("last4") or "").strip()

        if not national_id or not last4:
            messages.error(request, "أدخل السجل المدني وآخر 4 أرقام.")
            return redirect("candidates:login")

        user = authenticate(request, national_id=national_id, last4=last4)
        if not user:
            messages.error(request, "بيانات الدخول غير صحيحة.")
            return redirect("candidates:login")

        p = getattr(user, "profile", None)
        if not p or not getattr(p, "is_active", False):
            messages.error(request, "حسابك غير مفعّل. راجع الإدارة.")
            return redirect("candidates:login")

        login(request, user, backend="candidates.auth_backend.NationalIdLast4Backend")
        return redirect("candidates:home")

    return render(request, "candidates/login.html")


def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("candidates:login")


# ==========================================================
# Supervisor
# ==========================================================

@login_required
def supervisor_dashboard(request: HttpRequest) -> HttpResponse:
    p = require_role(request, {MemberProfile.ROLE_SUPERVISOR})
    if isinstance(p, HttpResponse):
        return p

    if not p.opportunity_id:
        messages.error(request, "لم يتم ربط المشرف بفرصة. راجع الإدارة.")
        return redirect("candidates:login")

    opp = p.opportunity
    qs = Candidate.objects.filter(opportunity=opp).order_by("full_name")

    q = (request.GET.get("q") or "").strip()
    qs = apply_search(qs, q)

    pending = qs.filter(file_score__isnull=True, file_not_eligible=False)
    done = qs.filter(Q(file_score__isnull=False) | Q(file_not_eligible=True))

    stats = {
        "total": qs.count(),
        "pending": pending.count(),
        "done": done.count(),
        "assigned": qs.filter(assigned_committee__isnull=False).count(),
    }

    return render(
        request,
        "candidates/supervisor_dashboard.html",
        {"opportunity": opp, "pending": pending, "done": done, "stats": stats, "q": q},
    )


# ==========================================================
# File Scoring (Unified) — Supervisor + Chair
# ==========================================================

@login_required
@require_http_methods(["GET", "POST"])
def file_score_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    تقييم الملف (موحّد):
    - المشرف: يقيّم مرشح ضمن فرصته.
    - رئيس اللجنة: يقيّم فقط مرشح ضمن لجنته (assigned_committee = لجنته).
    """
    p = require_role(request, {MemberProfile.ROLE_SUPERVISOR, MemberProfile.ROLE_CHAIR})
    if isinstance(p, HttpResponse):
        return p

    if p.role == MemberProfile.ROLE_SUPERVISOR:
        if not p.opportunity_id:
            messages.error(request, "لم يتم ربط المشرف بفرصة. راجع الإدارة.")
            return redirect("candidates:login")

        cand = get_object_or_404(Candidate, pk=pk, opportunity=p.opportunity)
        back_url = "candidates:supervisor_dashboard"
    else:
        if not p.committee_id:
            messages.error(request, "لم يتم ربط حسابك بلجنة. راجع الإدارة.")
            return redirect("candidates:login")

        cand = get_object_or_404(Candidate, pk=pk, assigned_committee=p.committee)
        back_url = "candidates:committee_dashboard"

    if cand.is_finalized:
        messages.error(request, "تم اعتماد هذا المرشح نهائياً ولا يمكن تعديله.")
        return redirect(back_url)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        with transaction.atomic():
            cand = Candidate.objects.select_for_update().get(pk=cand.pk)

            if cand.is_finalized:
                messages.error(request, "تم اعتماد هذا المرشح نهائياً ولا يمكن تعديله.")
                return redirect(back_url)

            if action == "not_eligible":
                reason = (request.POST.get("reason") or "").strip()
                cand.file_not_eligible = True
                cand.file_not_eligible_reason = reason
                cand.file_score = None
            else:
                v = parse_decimal_0_50(request.POST.get("score") or "")
                if v is None:
                    messages.error(request, "أدخل درجة صحيحة بين 0 و 50.")
                    return redirect("candidates:file_score", pk=cand.pk)

                cand.file_score = v
                cand.file_not_eligible = False
                cand.file_not_eligible_reason = ""

            cand.file_reviewer = request.user
            cand.file_scored_at = timezone.now()
            cand.save()

        messages.success(request, "تم حفظ تقييم الملف.")
        return redirect(back_url)

    return render(request, "candidates/file_score.html", {"c": cand, "back_url": back_url})


# ==========================================================
# Admin
# ==========================================================

@login_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    p = require_role(request, {MemberProfile.ROLE_ADMIN})
    if isinstance(p, HttpResponse):
        return p

    opp = get_active_opportunity_for_profile(p)
    if not opp:
        messages.error(request, "لا توجد فرصة فعّالة.")
        return redirect("candidates:login")

    qs = Candidate.objects.filter(opportunity=opp)
    total = qs.count()
    ready = qs.filter(Q(file_score__isnull=False) | Q(file_not_eligible=True)).count()
    assigned = qs.filter(assigned_committee__isnull=False).count()
    finalized = qs.filter(is_finalized=True).count()

    committees = Committee.objects.filter(opportunity=opp).order_by("name")
    committee_counts = (
        qs.filter(assigned_committee__isnull=False)
        .values("assigned_committee__name")
        .annotate(c=Count("id"))
        .order_by("assigned_committee__name")
    )

    return render(
        request,
        "candidates/admin_dashboard.html",
        {
            "opportunity": opp,
            "total": total,
            "ready": ready,
            "assigned": assigned,
            "finalized": finalized,
            "committees": committees,
            "committee_counts": committee_counts,
        },
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def distribution_view(request: HttpRequest) -> HttpResponse:
    opp = Opportunity.objects.filter(is_active=True).first()
    if not opp:
        messages.error(request, "لا توجد فرصة فعّالة.")
        return redirect("candidates:admin_dashboard")

    committees = Committee.objects.filter(opportunity=opp, is_open=True).order_by("name")

    ready_unassigned = (
        Candidate.objects.filter(opportunity=opp)
        .filter(Q(file_score__isnull=False) | Q(file_not_eligible=True))
        .filter(assigned_committee__isnull=True)
        .order_by("full_name")
    )

    q = (request.GET.get("q") or "").strip()
    ready_unassigned = apply_search(ready_unassigned, q)

    if request.method == "POST":
        try:
            cand_id = int(request.POST.get("candidate_id") or 0)
            committee_id = int(request.POST.get("committee_id") or 0)
        except ValueError:
            messages.error(request, "مدخلات غير صحيحة.")
            return redirect("candidates:distribution")

        if cand_id <= 0 or committee_id <= 0:
            messages.error(request, "اختر مرشحًا ولجنة.")
            return redirect("candidates:distribution")

        with transaction.atomic():
            cand = Candidate.objects.select_for_update().filter(pk=cand_id, opportunity=opp).first()
            com = Committee.objects.filter(pk=committee_id, opportunity=opp, is_open=True).first()

            if not cand:
                messages.error(request, "المرشح غير موجود.")
                return redirect("candidates:distribution")
            if not com:
                messages.error(request, "اللجنة غير موجودة أو غير مفتوحة.")
                return redirect("candidates:distribution")

            if cand.file_score is None and not cand.file_not_eligible:
                messages.error(request, "هذا المرشح غير جاهز للتوزيع بعد.")
                return redirect("candidates:distribution")

            if cand.assigned_committee_id:
                messages.info(request, "تم توزيع هذا المرشح مسبقاً.")
                return redirect("candidates:distribution")

            cand.assigned_committee = com
            cand.save(update_fields=["assigned_committee"])

        messages.success(request, "تم توزيع المرشح على اللجنة.")
        return redirect("candidates:distribution")

    return render(
        request,
        "candidates/distribution.html",
        {"opportunity": opp, "committees": committees, "ready": ready_unassigned, "q": q},
    )


# ==========================================================
# Committee
# ==========================================================

@login_required
def committee_dashboard(request: HttpRequest) -> HttpResponse:
    p = require_role(request, {MemberProfile.ROLE_MEMBER, MemberProfile.ROLE_CHAIR})
    if isinstance(p, HttpResponse):
        return p

    if not p.committee_id:
        messages.error(request, "لم يتم ربط حسابك بلجنة. راجع الإدارة.")
        return redirect("candidates:login")

    com = p.committee
    qs = Candidate.objects.filter(assigned_committee=com).order_by("full_name")

    q = (request.GET.get("q") or "").strip()
    qs = apply_search(qs, q)

    scored_ids = set(
        InterviewScore.objects.filter(committee=com, member=request.user).values_list("candidate_id", flat=True)
    )

    tasks = None
    if p.role == MemberProfile.ROLE_CHAIR:
        tasks = {
            "pending_file": qs.filter(file_score__isnull=True, file_not_eligible=False).count(),
            "pending_interview": qs.exclude(id__in=scored_ids).filter(is_finalized=False).count(),
            "pending_finalize": qs.filter(is_finalized=False).count(),
        }

    return render(
        request,
        "candidates/committee_dashboard.html",
        {
            "committee": com,
            "candidates": qs,
            "scored_ids": scored_ids,
            "is_chair": p.role == MemberProfile.ROLE_CHAIR,
            "q": q,
            "tasks": tasks,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def committee_score(request: HttpRequest, pk: int) -> HttpResponse:
    p = require_role(request, {MemberProfile.ROLE_MEMBER, MemberProfile.ROLE_CHAIR})
    if isinstance(p, HttpResponse):
        return p

    com = p.committee
    if not com:
        messages.error(request, "لم يتم ربط حسابك بلجنة.")
        return redirect("candidates:login")

    cand = get_object_or_404(Candidate, pk=pk, assigned_committee=com)

    if cand.is_finalized:
        messages.error(request, "تم اعتماد المرشح نهائياً.")
        return redirect("candidates:committee_dashboard")

    my_score = InterviewScore.objects.filter(committee=com, candidate=cand, member=request.user).first()

    if request.method == "POST":
        v = parse_decimal_0_50(request.POST.get("score") or "")
        notes = (request.POST.get("notes") or "").strip()

        if v is None:
            messages.error(request, "أدخل درجة صحيحة بين 0 و 50.")
            return redirect("candidates:committee_score", pk=cand.pk)

        with transaction.atomic():
            cand = Candidate.objects.select_for_update().get(pk=cand.pk)
            if cand.is_finalized:
                messages.error(request, "تم اعتماد المرشح نهائياً.")
                return redirect("candidates:committee_dashboard")

            InterviewScore.objects.update_or_create(
                committee=com,
                candidate=cand,
                member=request.user,
                defaults={"score": v, "notes": notes},
            )

        messages.success(request, "تم حفظ درجة المقابلة.")
        return redirect("candidates:committee_dashboard")

    return render(request, "candidates/committee_score.html", {"c": cand, "committee": com, "my_score": my_score})


@login_required
@require_http_methods(["GET", "POST"])
def chair_finalize(request: HttpRequest, pk: int) -> HttpResponse:
    p = require_role(request, {MemberProfile.ROLE_CHAIR})
    if isinstance(p, HttpResponse):
        return p

    com = p.committee
    if not com:
        messages.error(request, "لم يتم ربط حسابك بلجنة.")
        return redirect("candidates:login")

    cand = get_object_or_404(Candidate, pk=pk, assigned_committee=com)

    scores = list(
        InterviewScore.objects.filter(committee=com, candidate=cand)
        .select_related("member")
        .order_by("created_at")
    )

    avg = Decimal(str(cand.interview_avg(com)))
    total = Decimal(str(cand.final_score(com)))

    prev = FinalDecision.objects.filter(committee=com, candidate=cand).first()

    if request.method == "POST":
        nominated = (request.POST.get("is_nominated") or "") == "1"
        reason = (request.POST.get("reason") or "").strip()

        with transaction.atomic():
            cand = Candidate.objects.select_for_update().get(pk=cand.pk)
            if cand.is_finalized:
                messages.info(request, "تم اعتماد المرشح مسبقاً.")
                return redirect("candidates:committee_dashboard")

            FinalDecision.objects.update_or_create(
                committee=com,
                candidate=cand,
                defaults={
                    "is_nominated": nominated,
                    "reason": reason,
                    "final_score_value": total,
                    "submitted_by": request.user,
                },
            )

            cand.is_finalized = True
            cand.finalized_by = request.user
            cand.finalized_at = timezone.now()
            cand.save(update_fields=["is_finalized", "finalized_by", "finalized_at"])

        messages.success(request, "تم اعتماد النتيجة وإرسالها للإدارة.")
        return redirect("candidates:committee_dashboard")

    return render(
        request,
        "candidates/chair_finalize.html",
        {"c": cand, "committee": com, "scores": scores, "avg": avg, "total": total, "prev": prev},
    )


# ==========================================================
# Backward compatibility (optional)
# ==========================================================

@login_required
@require_http_methods(["GET", "POST"])
def supervisor_file_score(request: HttpRequest, pk: int) -> HttpResponse:
    """
    توافق خلفي للمسار القديم:
    /supervisor/candidate/<pk>/
    يحوّله للتقييم الموحد file_score_view
    """
    return file_score_view(request, pk)
