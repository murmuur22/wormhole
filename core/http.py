import json
import hashlib
import re
from django.middleware.csrf import CsrfViewMiddleware
from django.views.decorators.csrf import csrf_exempt
from core.models import ApiToken
from functools import wraps
from django.views.decorators.debug import sensitive_variables
from django.http import JsonResponse
from django.db import DatabaseError
from django.core.exceptions import RequestDataTooBig
from core.storage import Rejected


def payload(request):
    if len(request.body) > 16384:
        raise ValueError("Request too large")
    value = json.loads(request.body)
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value


def api(admin=False):
    def decorate(view):
        @wraps(view)
        @sensitive_variables()
        def wrapped(request, *args, **kwargs):
            request.api_token = None
            authorization = request.headers.get("Authorization")
            if authorization is not None:
                if admin or not re.fullmatch(
                    r"Bearer [A-Za-z0-9_-]{43}", authorization
                ):
                    return JsonResponse({"error": "Invalid token"}, status=401)
                token = (
                    ApiToken.objects.filter(
                        digest=hashlib.sha256(authorization[7:].encode()).hexdigest(),
                        active=True,
                        user__is_active=True,
                    )
                    .select_related("user")
                    .first()
                )
                if not token:
                    return JsonResponse({"error": "Invalid token"}, status=401)
                request.user, request.api_token = token.user, token
            if not request.user.is_authenticated or not request.user.is_active:
                return JsonResponse({"error": "Authentication required"}, status=401)
            if not request.api_token:
                refused = CsrfViewMiddleware(lambda r: None).process_view(
                    request, lambda r: None, (), {}
                )
                if refused:
                    return refused
            if admin and not request.user.is_superuser:
                return JsonResponse(
                    {"error": "Administrator access required"}, status=403
                )
            try:
                return view(request, *args, **kwargs)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return JsonResponse({"error": "Invalid request"}, status=400)
            except Rejected as exc:
                return JsonResponse({"error": exc.message}, status=exc.status)
            except RequestDataTooBig:
                return JsonResponse({"error": "Request too large"}, status=413)
            except (OSError, DatabaseError):
                return JsonResponse(
                    {"error": "Storage unavailable; retry later"}, status=503
                )

        return csrf_exempt(wrapped)

    return decorate
