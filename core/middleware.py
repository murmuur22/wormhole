import os
from urllib.parse import urlsplit
from django.http import HttpResponseBadRequest


class Boundaries:
    def __init__(self, get_response):
        self.get_response = get_response
        self.ancestor = os.environ.get("WORMHOLE_FRAME_ANCESTOR", "")
        if self.ancestor:
            parsed = urlsplit(self.ancestor)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in self.ancestor
            ):
                raise ValueError("Frame ancestor must be an explicit HTTPS origin")

    def __call__(self, request):
        request.get_host()  # Apply ALLOWED_HOSTS even to health/static routes.
        from django.http import HttpResponse

        try:
            size = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return HttpResponseBadRequest("Invalid content length")
        if size < 0:
            return HttpResponseBadRequest("Invalid content length")
        if size > 600000:
            return HttpResponse("Request too large", status=413)
        response = self.get_response(request)
        response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors "
            + (self.ancestor or "'none'")
        )
        if self.ancestor and response.has_header("X-Frame-Options"):
            del response["X-Frame-Options"]
        return response
