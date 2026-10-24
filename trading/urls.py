from django.urls import path

from trading import views

app_name = "trading"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("momentum/", views.momentum_scores, name="momentum_scores"),
    path("signals/", views.trading_signals, name="trading_signals"),
    path("api/recalculate-momentum/", views.recalculate_momentum, name="recalculate_momentum"),
    path("api/generate-signals/", views.generate_signals, name="generate_signals"),
]
