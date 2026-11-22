import re
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from core.http import api, payload
from core.models import Bucket, Grant, ApiToken
import secrets
import hashlib
from django.views.decorators.debug import sensitive_variables


@require_POST
@api(admin=True)
def create_bucket(request):
    data = payload(request)
    name, folder = data["name"], data["folder"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError("Invalid name")
    if (
        not isinstance(folder, str)
        or len(folder) > 400
        or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}(?:/[a-zA-Z0-9_-]{1,64}){0,14}", folder
        )
    ):
        raise ValueError("Invalid folder")
    parent_id = data.get("parent_id")
    parent = (
        Bucket.objects.filter(pk=parent_id).first() if type(parent_id) is int else None
    )
    if parent_id is not None and parent is None:
        raise ValueError("Invalid parent")
    if parent and (
        not folder.startswith(parent.folder + "/") or parent.label().count(" / ") >= 13
    ):
        raise ValueError("Sub-bucket must be inside parent")
    try:
        bucket = Bucket.objects.create(name=name.strip(), folder=folder, parent=parent)
    except IntegrityError:
        return JsonResponse({"error": "Destination already exists"}, status=409)
    return JsonResponse({"id": bucket.pk}, status=201)


@require_POST
@api(admin=True)
def change_grant(request):
    data = payload(request)
    if (
        type(data["user_id"]) is not int
        or type(data["bucket_id"]) is not int
        or type(data["allowed"]) is not bool
    ):
        raise ValueError("Invalid grant")
    user = get_user_model().objects.filter(pk=data["user_id"]).first()
    bucket = Bucket.objects.filter(pk=data["bucket_id"]).first()
    if not user or not bucket:
        raise ValueError("Unknown account or bucket")
    if data["allowed"]:
        Grant.objects.get_or_create(user=user, bucket=bucket)
    else:
        Grant.objects.filter(user=user, bucket=bucket).delete()
    return JsonResponse({"ok": True})


@require_POST
@api(admin=True)
@sensitive_variables()
def create_token(request):
    data = payload(request)
    if (
        type(data["user_id"]) is not int
        or not isinstance(data["label"], str)
        or not 1 <= len(data["label"]) <= 120
    ):
        raise ValueError("Invalid account or label")
    ids = data["bucket_ids"]
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 100
        or any(type(i) is not int for i in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Invalid scope")
    user = get_user_model().objects.filter(pk=data["user_id"], is_active=True).first()
    if not user or Grant.objects.filter(user=user, bucket_id__in=ids).count() != len(
        ids
    ):
        raise ValueError("Token must be a subset of account grants")
    raw = secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        user=user, label=data["label"], digest=hashlib.sha256(raw.encode()).hexdigest()
    )
    token.buckets.set(ids)
    return JsonResponse({"id": token.pk, "token": raw}, status=201)


@require_POST
@api(admin=True)
@sensitive_variables()
def create_account(request):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    data = payload(request)
    username, password = data["username"], data["password"]
    if (
        not isinstance(username, str)
        or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", username)
        or not isinstance(password, str)
        or len(password) > 128
    ):
        raise ValueError("Invalid account")
    try:
        validate_password(password)
    except ValidationError:
        raise ValueError("Password requirements not met")
    if get_user_model().objects.count() >= 1000:
        raise ValueError("Account limit reached")
    try:
        user = get_user_model().objects.create_user(username, password=password)
    except IntegrityError:
        return JsonResponse({"error": "Username already exists"}, status=409)
    return JsonResponse({"id": user.pk}, status=201)


@require_POST
@api(admin=True)
def account_status(request):
    data = payload(request)
    if type(data["user_id"]) is not int or type(data["active"]) is not bool:
        raise ValueError("Invalid account status")
    user = (
        get_user_model().objects.filter(pk=data["user_id"], is_superuser=False).first()
    )
    if not user:
        raise ValueError("Account missing or administrator protected")
    user.is_active = data["active"]
    user.save(update_fields=["is_active"])
    if not user.is_active:
        ApiToken.objects.filter(user=user).update(active=False)
    return JsonResponse({"ok": True})


@require_POST
@api(admin=True)
def revoke_token(request):
    data = payload(request)
    if type(data["id"]) is not int:
        raise ValueError("Invalid token")
    ApiToken.objects.filter(pk=data["id"]).update(active=False)
    return JsonResponse({"ok": True})


@api(admin=True)
def state(request):
    from core.models import Upload

    return JsonResponse(
        {
            "accounts": [
                {
                    "id": u.pk,
                    "name": u.username,
                    "active": u.is_active,
                    "admin": u.is_superuser,
                }
                for u in get_user_model().objects.order_by("id")[:1000]
            ],
            "buckets": [
                {
                    "id": b.pk,
                    "name": b.label(),
                    "folder": b.folder,
                    "parent_id": b.parent_id,
                }
                for b in Bucket.objects.select_related("parent").order_by("id")[:1000]
            ],
            "grants": list(Grant.objects.values("user_id", "bucket_id")[:10000]),
            "tokens": [
                {"id": t.pk, "user_id": t.user_id, "label": t.label, "active": t.active}
                for t in ApiToken.objects.order_by("-id")[:1000]
            ],
            "uploads": [
                {
                    "id": str(u.pk),
                    "user_id": u.user_id,
                    "name": u.original_name,
                    "size": u.size,
                    "offset": u.offset,
                    "state": u.state,
                    "bucket_id": u.bucket_id,
                    "sha256": u.sha256,
                }
                for u in Upload.objects.order_by("-created")[:100]
            ],
        }
    )
