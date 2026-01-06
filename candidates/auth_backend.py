from __future__ import annotations

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User

from .models import MemberProfile


class NationalIdLast4Backend(BaseBackend):
    """
    تسجيل دخول مبني على:
    - national_id
    - last4
    يتم البحث في MemberProfile وربطه بالمستخدم.
    """

    def authenticate(
        self,
        request,
        national_id: str | None = None,
        last4: str | None = None,
        required_role: str | None = None,  # اختياري (للتوافق مع نسخ قديمة)
    ):
        if not national_id or not last4:
            return None

        prof = (
            MemberProfile.objects
            .select_related("user")
            .filter(national_id=national_id, last4=last4)
            .first()
        )
        if not prof or not prof.is_active:
            return None

        if required_role and prof.role != required_role:
            return None

        return prof.user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
