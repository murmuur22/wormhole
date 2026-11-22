FROM python:3.12-slim-bookworm AS build
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.12.10 && uv sync --locked --no-dev --python /usr/local/bin/python --no-managed-python

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY --from=build /build/.venv /opt/venv
COPY core ./core
COPY wormhole ./wormhole
COPY static ./static
COPY templates ./templates
COPY manage.py pyproject.toml uv.lock ./
RUN groupadd --gid 10001 wormhole && useradd --uid 10001 --gid 10001 --no-create-home wormhole
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()"
CMD ["python", "-m", "gunicorn", "wormhole.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "180", "--access-logfile", "-", "--error-logfile", "-"]
