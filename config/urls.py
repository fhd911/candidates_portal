from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # ✅ يوفر /accounts/login/ و /accounts/logout/ ... إلخ
    path("accounts/", include("django.contrib.auth.urls")),

    path("", include("candidates.urls")),
]
