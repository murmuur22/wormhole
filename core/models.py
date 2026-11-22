import uuid
from django.conf import settings
from django.db import models


class LoginWindow(models.Model):
    key = models.CharField(max_length=64, unique=True)
    started = models.DateTimeField()
    hits = models.PositiveIntegerField(default=0)


class Bucket(models.Model):
    name = models.CharField(max_length=120)
    folder = models.CharField(max_length=400, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    def label(self):
        names, node = [], self
        for _ in range(16):
            if node is None:
                return " / ".join(reversed(names))
            names.append(node.name)
            node = node.parent
        raise ValueError("Bucket hierarchy too deep")


class Grant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bucket = models.ForeignKey(Bucket, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "bucket"], name="unique_upload_grant"
            )
        ]


class ApiToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    buckets = models.ManyToManyField(Bucket)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)


class Upload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    token = models.ForeignKey(ApiToken, null=True, on_delete=models.PROTECT)
    bucket = models.ForeignKey(Bucket, on_delete=models.PROTECT)
    original_name = models.CharField(max_length=240)
    size = models.BigIntegerField()
    offset = models.BigIntegerField(default=0)
    expected_sha256 = models.CharField(max_length=64, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=16, default="pending")
    stored_name = models.CharField(max_length=300, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    completed = models.DateTimeField(null=True)
