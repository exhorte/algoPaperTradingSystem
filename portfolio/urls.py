from django.urls import path

from portfolio import views

app_name = "portfolio"

urlpatterns = [
    path("", views.portfolio_list, name="list"),
    path("create/", views.portfolio_create, name="create"),
    path("create/callback/", views.portfolio_create_callback, name="create_callback"),
    path("create/finish/", views.portfolio_create_finish, name="create_finish"),
    path("<int:pk>/", views.portfolio_detail, name="detail"),
    path("<int:pk>/sync/", views.portfolio_sync, name="sync"),
    path("<int:pk>/rebalance/", views.portfolio_rebalance, name="rebalance"),
]
