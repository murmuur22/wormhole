from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction
from django.db.models import F
from core.http import api, payload
from core import storage


def token_id(request):
    token = getattr(request, "api_token", None)
    return token.pk if token else None


@require_POST
@api()
def begin(request):
    return JsonResponse(
        storage.begin(request.user, request.api_token, payload(request)), status=201
    )


@require_http_methods(["PUT"])
@api()
def chunk(request, upload_id):
    raw = request.GET.get("offset", "")
    if not raw.isdecimal() or len(raw) > 12:
        raise ValueError("Invalid offset")
    return JsonResponse(
        storage.append(
            request.user,
            upload_id,
            int(raw),
            request.body,
            request.headers.get("X-Chunk-SHA256"),
            token_id(request),
        )
    )


@require_POST
@api()
def finish(request, upload_id):
    return JsonResponse(storage.finish(request.user, upload_id, token_id(request)))


@require_http_methods(["DELETE"])
@api()
def cancel(request, upload_id):
    with storage.upload_lock(upload_id, request.user.pk), transaction.atomic():
        storage.Upload.objects.filter(pk=upload_id, user_id=request.user.pk).update(
            offset=F("offset")
        )
        upload = storage.get_upload(upload_id, request.user.pk, token_id(request))
        if upload.state == "complete":
            raise storage.Rejected("Completed archives cannot be deleted", 409)
        upload.state = "cancelled"
        upload.save(update_fields=["state"])
    with storage.child_directory(storage.settings.STATE_DIR, "parts") as fd:
        try:
            storage.os.unlink(str(upload.pk), dir_fd=fd)
        except FileNotFoundError:
            pass
    return JsonResponse({"ok": True})
