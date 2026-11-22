import os
import secrets
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.storage import directory, verify_archive


class Command(BaseCommand):
    help = "Test archive identity, write/fsync, hard-link publication and readback with disposable files."

    def handle(self, *args, **options):
        name = ".wormhole-probe-" + secrets.token_hex(16)
        linked = name + "-linked"
        try:
            with directory(settings.ARCHIVE_ROOT) as fd:
                verify_archive(fd)
                created = False
                published = False
                try:
                    file_fd = os.open(
                        name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=fd,
                    )
                    created = True
                    with os.fdopen(file_fd, "wb") as file:
                        file.write(b"Wormhole disposable storage probe\n")
                        file.flush()
                        os.fsync(file.fileno())
                    os.link(
                        name,
                        linked,
                        src_dir_fd=fd,
                        dst_dir_fd=fd,
                        follow_symlinks=False,
                    )
                    published = True
                    os.fsync(fd)
                    reader = os.open(
                        linked, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                    )
                    with os.fdopen(reader, "rb") as file:
                        if file.read(100) != b"Wormhole disposable storage probe\n":
                            raise CommandError("Archive readback mismatch")
                finally:
                    if published:
                        os.unlink(linked, dir_fd=fd)
                    if created:
                        os.unlink(name, dir_fd=fd)
                    os.fsync(fd)
        except OSError as exc:
            raise CommandError(
                "Archive required filesystem operation failed; check mount semantics and permissions"
            ) from exc
        self.stdout.write(
            "Archive identity and required filesystem operations passed; probe files removed."
        )
