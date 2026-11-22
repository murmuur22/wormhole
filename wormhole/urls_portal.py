from django.contrib.auth.views import LogoutView
from django.urls import path
from core.login import ProtectedLogin as LoginView
from core.views import health, buckets, portal, asset
from core.upload_views import begin, chunk, finish, cancel

urlpatterns = [
    path("", portal),
    path("health", health),
    path("static/<path:name>", asset),
    path("login/", LoginView.as_view(template_name="login.html", next_page="/")),
    path("logout/", LogoutView.as_view(next_page="/login/")),
    path("api/buckets", buckets),
    path("api/uploads", begin),
    path("api/uploads/<uuid:upload_id>", cancel),
    path("api/uploads/<uuid:upload_id>/chunk", chunk),
    path("api/uploads/<uuid:upload_id>/finish", finish),
]
