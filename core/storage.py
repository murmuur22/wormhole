import contextlib
import fcntl
import hashlib
import os
import re
import stat
import time
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
from core.models import ApiToken, Grant, Upload


class Rejected(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


@contextlib.contextmanager
def directory(path):
    """Walk real directories by descriptors; do not follow any symlink component."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def child_directory(root, name):
    with directory(root) as fd:
        try:
            os.mkdir(name, mode=0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            yield child
        finally:
            os.close(child)


@contextlib.contextmanager
def upload_lock(upload_id=None, user_id=None):
    name = "uploads.lock"
    if upload_id is not None:
        if not Upload.objects.filter(pk=upload_id, user_id=user_id).exists():
            raise Rejected("Upload not found", 404)
        name = "upload-" + str(upload_id) + ".lock"
    with directory(settings.STATE_DIR) as fd:
        lock = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=fd,
        )
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise Rejected("Invalid lock", 503)
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise Rejected("Archive busy; retry later", 503)
                    time.sleep(0.02)
            yield
        finally:
            os.close(lock)


def verify_archive(root_fd=None):
    def check(fd):
        marker = os.open(
            ".wormhole-archive-id",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=fd,
        )
        with os.fdopen(marker, "rb") as file:
            info = os.fstat(file.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or file.read(65) != (settings.ARCHIVE_ID + "\n").encode()
            ):
                raise Rejected("Archive identity unavailable", 503)

    if root_fd is None:
        with directory(settings.ARCHIVE_ROOT) as fd:
            check(fd)
    else:
        check(root_fd)


def allowed(user_id, bucket_id, token_id=None):
    if not get_user_model().objects.filter(pk=user_id, is_active=True).exists():
        raise Rejected("Account disabled", 403)
    if (
        token_id
        and not ApiToken.objects.filter(
            pk=token_id, user_id=user_id, active=True, buckets__pk=bucket_id
        ).exists()
    ):
        raise Rejected("Token revoked", 403)
    if not Grant.objects.filter(user_id=user_id, bucket_id=bucket_id).exists():
        raise Rejected("Upload not permitted", 403)


def get_upload(upload_id, user_id, requesting_token_id=None, allow_finalizing=False):
    upload = (
        Upload.objects.filter(pk=upload_id, user_id=user_id)
        .select_related("bucket")
        .first()
    )
    if not upload:
        raise Rejected("Upload not found", 404)
    allowed(user_id, upload.bucket_id, upload.token_id)
    if requesting_token_id:
        allowed(user_id, upload.bucket_id, requesting_token_id)
    if upload.state != "complete" and upload.created < timezone.now() - timedelta(
        seconds=settings.UPLOAD_TTL_SECONDS
    ):
        raise Rejected("Upload expired", 410)
    accepted = {"pending", "complete"} | (
        {"finalizing", "reconcile"} if allow_finalizing else set()
    )
    if upload.state not in accepted:
        raise Rejected("Upload unavailable or needs operator reconciliation", 409)
    return upload


def receipt(upload):
    return {
        "id": str(upload.pk),
        "name": upload.original_name,
        "bucket_id": upload.bucket_id,
        "size": upload.size,
        "sha256": upload.sha256,
        "state": upload.state,
    }


def begin(user, token, data):
    name, size, bucket_id = data["name"], data["size"], data["bucket_id"]
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 240
        or name in {".", ".."}
        or any(ord(c) < 32 or c in "/\\" for c in name)
    ):
        raise Rejected("Invalid filename")
    if (
        type(size) is not int
        or not 0 <= size <= settings.MAX_FILE_BYTES
        or type(bucket_id) is not int
    ):
        raise Rejected("Invalid file size or destination")
    expected = data.get("sha256", "")
    if not isinstance(expected, str) or (
        expected and not re.fullmatch("[0-9a-f]{64}", expected)
    ):
        raise Rejected("Invalid checksum")
    verify_archive()
    with upload_lock(), transaction.atomic():
        allowed(user.pk, bucket_id, token.pk if token else None)
        pending = Upload.objects.filter(
            state__in=["pending", "finalizing", "reconcile"]
        )
        personal = pending.filter(user=user)
        if (
            personal.count() >= settings.MAX_PENDING_PER_ACCOUNT
            or (personal.aggregate(total=Sum("size"))["total"] or 0) + size
            > settings.MAX_PENDING_BYTES_PER_ACCOUNT
            or (pending.aggregate(total=Sum("size"))["total"] or 0) + size
            > settings.MAX_PENDING_BYTES
        ):
            raise Rejected("Pending upload limit reached", 429)
        upload = Upload.objects.create(
            user=user,
            token=token,
            bucket_id=bucket_id,
            original_name=name,
            size=size,
            expected_sha256=expected,
        )
        with child_directory(settings.STATE_DIR, "parts") as fd:
            part = os.open(
                str(upload.pk),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=fd,
            )
            os.close(part)
    return {"id": str(upload.pk), "offset": 0, "chunk_bytes": settings.CHUNK_BYTES}


def append(user, upload_id, offset, body, digest, requesting_token_id=None):
    if (
        not body
        or len(body) > settings.CHUNK_BYTES
        or not re.fullmatch("[0-9a-f]{64}", digest or "")
        or hashlib.sha256(body).hexdigest() != digest
    ):
        raise Rejected("Invalid chunk")
    with upload_lock(upload_id, user.pk), transaction.atomic():
        Upload.objects.filter(pk=upload_id, user_id=user.pk).update(offset=F("offset"))
        upload = get_upload(upload_id, user.pk, requesting_token_id)
        if (
            upload.state != "pending"
            or offset != upload.offset
            or upload.offset + len(body) > upload.size
        ):
            raise Rejected("Chunk offset conflict", 409)
        with child_directory(settings.STATE_DIR, "parts") as fd:
            part = os.open(
                str(upload.pk), os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
            )
            with os.fdopen(part, "r+b") as file:
                info = os.fstat(file.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size < upload.offset
                ):
                    raise Rejected("Upload storage invalid", 503)
                file.truncate(upload.offset)
                file.seek(upload.offset)
                file.write(body)
                file.flush()
                os.fsync(file.fileno())
            upload.offset += len(body)
            upload.save(update_fields=["offset"])
    return {"id": str(upload.pk), "offset": upload.offset}


@contextlib.contextmanager
def bucket_directory(bucket):
    if not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,64}(?:/[a-zA-Z0-9_-]{1,64}){0,14}", bucket.folder
    ):
        raise Rejected("Invalid archive mapping", 503)
    with directory(settings.ARCHIVE_ROOT) as root:
        verify_archive(root)
        fd = os.dup(root)
        try:
            for name in bucket.folder.split("/"):
                try:
                    os.mkdir(name, 0o750, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                os.close(fd)
                fd = next_fd
            yield fd
        finally:
            os.close(fd)


def finish(user, upload_id, requesting_token_id=None):
    from core.finalization import finish as finalize

    return finalize(user, upload_id, requesting_token_id)


def cleanup_expired():
    removed = 0
    with upload_lock():
        cutoff = timezone.now() - timedelta(seconds=settings.UPLOAD_TTL_SECONDS)
        Upload.objects.filter(state="pending", created__lt=cutoff).update(
            state="expired"
        )
        with child_directory(settings.STATE_DIR, "parts") as fd:
            for name in os.listdir(fd):
                if not re.fullmatch("[0-9a-f-]{36}", name):
                    continue
                record = Upload.objects.filter(pk=name).first()
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if record and record.state in {"pending", "finalizing", "reconcile"}:
                    continue
                if record is None and info.st_mtime > cutoff.timestamp():
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise Rejected("Unexpected temporary storage entry", 503)
                os.unlink(name, dir_fd=fd)
                removed += 1
    return removed
