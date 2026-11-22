import tomllib
from pathlib import Path
from django.http import JsonResponse
from core.http import api
from core.models import Bucket
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.http import FileResponse, Http404

VERSION = tomllib.loads(
    (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
)["project"]["version"]


def health(request):
    from django.conf import settings
    from django.db import DatabaseError
    from core.storage import verify_archive, Rejected
    from core.models import Upload

    try:
        verify_archive()
        Upload.objects.exists()
    except (OSError, Rejected, DatabaseError):
        return JsonResponse(
            {
                "status": "unavailable",
                "version": VERSION,
                "schema": 1,
                "surface": settings.SURFACE,
            },
            status=503,
        )
    return JsonResponse(
        {"status": "ok", "version": VERSION, "schema": 1, "surface": settings.SURFACE}
    )


@login_required(login_url="/login/")
def portal(request):
    return render(request, "portal.html")


@user_passes_test(
    lambda user: user.is_active and user.is_superuser, login_url="/login/"
)
def dashboard(request):
    return render(request, "admin.html")


def asset(request, name):
    allowed = {
        "app.css",
        "forms.css",
        "portal.js",
        "admin.js",
        "vendor/three.module.js",
        "vendor/three.core.js",
        "vendor/THREE-LICENSE.txt",
    }
    if name not in allowed:
        raise Http404
    mime = (
        "text/css"
        if name.endswith(".css")
        else "text/javascript"
        if name.endswith(".js")
        else "text/plain"
    )
    return FileResponse(
        (Path(__file__).resolve().parent.parent / "static" / name).open("rb"),
        content_type=mime,
    )


@require_GET
@api()
def buckets(request):
    visible = (
        Bucket.objects.filter(grant__user=request.user)
        .select_related("parent")
        .order_by("id")
    )
    if getattr(request, "api_token", None):
        visible = visible.filter(apitoken=request.api_token)
    return JsonResponse({"buckets": [{"id": b.pk, "name": b.label()} for b in visible]})
