import hashlib
import unicodedata
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.views import LoginView
from django.db import transaction, DatabaseError
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from core.models import LoginWindow


class ProtectedLogin(LoginView):
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        now = timezone.now()
        # A proxy peer is shared by many real users. Do not turn that address
        # into a global lockout, and never let portal attempts throttle admin.
        username = unicodedata.normalize(
            "NFKC", request.POST.get("username", "").strip()
        ).casefold()
        key = hashlib.sha256(
            (settings.SURFACE + ":user:" + username).encode()
        ).hexdigest()
        try:
            with transaction.atomic():
                LoginWindow.objects.filter(
                    started__lt=now - timedelta(minutes=15)
                ).delete()
                window, _ = LoginWindow.objects.get_or_create(
                    key=key, defaults={"started": now}
                )
                LoginWindow.objects.filter(pk=window.pk).update(hits=F("hits") + 1)
                window.refresh_from_db()
                if window.hits > 5:
                    return HttpResponse(
                        "Too many sign-in attempts for this account. Try again later.",
                        status=429,
                        headers={"Retry-After": "900"},
                    )
            result = super().post(request, *args, **kwargs)
            if result.status_code == 302:
                LoginWindow.objects.filter(key=key).delete()
            return result
        except DatabaseError:
            return HttpResponse(
                "Sign-in temporarily unavailable. Retry later.", status=503
            )
