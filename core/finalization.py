"""Per-transfer archive copying with short, authority-fenced publication transactions."""

import contextlib
import hashlib
import os
import re
import stat
from django.db import transaction, DatabaseError
from django.db.models import F
from django.utils import timezone
from core import storage as s
from core.models import Upload


def finish(user, upload_id, requesting_token_id=None):
    with s.upload_lock(upload_id, user.pk), contextlib.ExitStack() as stack:
        # Reserve this transfer in a short transaction. No NAS copying is done
        # while holding the shared SQLite writer lock or global admission lock.
        with transaction.atomic():
            Upload.objects.filter(pk=upload_id, user_id=user.pk).update(
                offset=F("offset")
            )
            upload = s.get_upload(
                upload_id, user.pk, requesting_token_id, allow_finalizing=True
            )
            if upload.state == "complete":
                return s.receipt(upload)
            previous_attempt = upload.state in {"finalizing", "reconcile"}
            if previous_attempt:
                Upload.objects.filter(pk=upload.pk).update(state="reconcile")
            else:
                if upload.offset != upload.size:
                    raise s.Rejected("Upload incomplete", 409)
                Upload.objects.filter(pk=upload.pk).update(state="finalizing")
        if previous_attempt:
            raise s.Rejected(
                "Upload needs operator reconciliation; no existing file was changed",
                409,
            )
        incoming = ".incoming-" + str(upload.pk)
        stored = (
            str(upload.pk)
            + "-"
            + re.sub(r"[^a-zA-Z0-9._-]", "_", upload.original_name)[:180]
        )
        dest = None
        linked = incoming_created = uncertain = False
        try:
            parts = stack.enter_context(
                s.child_directory(s.settings.STATE_DIR, "parts")
            )
            dest = stack.enter_context(s.bucket_directory(upload.bucket))
            for name in (incoming, stored):
                try:
                    os.stat(name, dir_fd=dest, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                uncertain = True
                raise s.Rejected(
                    "Upload needs operator reconciliation; existing file preserved", 409
                )
            source_fd = os.open(
                str(upload.pk),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parts,
            )
            with os.fdopen(source_fd, "rb") as source:
                info = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size != upload.size
                ):
                    raise s.Rejected("Upload storage invalid", 503)
                target_fd = os.open(
                    incoming,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o640,
                    dir_fd=dest,
                )
                incoming_created = True
                hasher = hashlib.sha256()
                with os.fdopen(target_fd, "wb") as target:
                    while block := source.read(1024 * 1024):
                        hasher.update(block)
                        target.write(block)
                    target.flush()
                    os.fsync(target.fileno())
            actual = hasher.hexdigest()
            if upload.expected_sha256 and actual != upload.expected_sha256:
                raise s.Rejected("File checksum mismatch", 409)
            # Recheck all live authority after the potentially slow copy, fenced
            # by a DB writer lock. Only the short publication/fsync is inside.
            with transaction.atomic():
                Upload.objects.filter(pk=upload_id, user_id=user.pk).update(
                    offset=F("offset")
                )
                live = s.get_upload(
                    upload_id, user.pk, requesting_token_id, allow_finalizing=True
                )
                if live.state != "finalizing":
                    raise s.Rejected("Upload state conflict", 409)
                s.verify_archive()
                try:
                    os.link(
                        incoming,
                        stored,
                        src_dir_fd=dest,
                        dst_dir_fd=dest,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    uncertain = True
                    raise s.Rejected(
                        "Publication conflict needs operator reconciliation", 409
                    ) from None
                linked = True
                os.unlink(incoming, dir_fd=dest)
                incoming_created = False
                os.fsync(dest)
                live.sha256, live.stored_name, live.state, live.completed = (
                    actual,
                    stored,
                    "complete",
                    timezone.now(),
                )
                live.save(update_fields=["sha256", "stored_name", "state", "completed"])
            upload = live
        except Exception:
            if linked:
                try:
                    os.unlink(stored, dir_fd=dest)
                    os.fsync(dest)
                except OSError:
                    uncertain = True
            if incoming_created:
                try:
                    os.unlink(incoming, dir_fd=dest)
                except OSError:
                    uncertain = True
            try:
                Upload.objects.filter(pk=upload_id, state="finalizing").update(
                    state="reconcile" if uncertain else "pending"
                )
            except DatabaseError:
                # A durable 'finalizing' row also refuses retries and signals
                # reconciliation; never claim success or erase uncertain files.
                pass
            raise
        try:
            os.unlink(str(upload.pk), dir_fd=parts)
        except OSError:
            pass
        return s.receipt(upload)
