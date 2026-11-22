from django.urls import path
from django.contrib.auth.views import LogoutView
from core.login import ProtectedLogin as LoginView
from core.views import health, dashboard, asset
from core.admin_views import (
    create_account,
    account_status,
    revoke_token,
    state,
    create_bucket,
    change_grant,
    create_token,
)

urlpatterns = [
    path("health", health),
    path("admin/", dashboard),
    path("login/", LoginView.as_view(template_name="login.html", next_page="/admin/")),
    path("logout/", LogoutView.as_view(next_page="/login/")),
    path("static/<path:name>", asset),
    path("admin/api/accounts", create_account),
    path("admin/api/accounts/status", account_status),
    path("admin/api/tokens/revoke", revoke_token),
    path("admin/api/state", state),
    path("admin/api/buckets", create_bucket),
    path("admin/api/grants", change_grant),
    path("admin/api/tokens", create_token),
]
