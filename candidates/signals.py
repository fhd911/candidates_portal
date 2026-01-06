# candidates/signals.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import MemberProfile

User = get_user_model()


@receiver(post_save, sender=User)
def ensure_profile(sender, instance: User, created: bool, **kwargs):
    """
    Ensure every user has a MemberProfile.

    Important:
    - Default role MUST be a non-committee role (because member/chair require committee).
    - So we default to 'supervisor' (safe) to avoid IntegrityError/constraint failures.
    """
    if not created:
        return

    # إذا تم إنشاء المستخدم من مكان آخر وكان لديه profile بالفعل، لا نكرر
    if hasattr(instance, "profile"):
        # related_name="profile" عادةً، لكن hasattr قد يرجع True حتى لو غير موجود أحيانًا
        try:
            _ = instance.profile
            return
        except Exception:
            pass

    # ✅ اختر دور افتراضي آمن لا يتطلب committee
    default_role = "supervisor"  # بدّلها إلى "admin" إذا رغبت

    # لو تغيرت الـ choices مستقبلًا، نسوي fallback لأول خيار متاح
    try:
        choices = [c[0] for c in MemberProfile._meta.get_field("role").choices]
        if default_role not in choices and choices:
            default_role = choices[0]
    except Exception:
        pass

    MemberProfile.objects.create(
        user=instance,
        role=default_role,
        is_active=False,
        committee=None,
    )
