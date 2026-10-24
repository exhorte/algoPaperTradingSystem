from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("portfolios/", include("portfolio.urls")),
    path("", include("trading.urls")),
]
