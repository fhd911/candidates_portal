from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),

    # (اختياري) صفحات تسجيل الدخول الافتراضية لـ Django
    # مفيدة للإدارة فقط إذا كنت تستخدم /accounts/login/
    path("accounts/", include("django.contrib.auth.urls")),

    # نظام المرشحين (يدير /login/ و /logout/ واللوحات)
    path("", include("candidates.urls")),
]
