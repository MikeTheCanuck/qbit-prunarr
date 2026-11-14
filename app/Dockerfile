# Build stage: full Ubuntu 24.04 with pip, used only to assemble the venv.
FROM ubuntu:24.04 AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3.12-venv \
 && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /venv
COPY requirements.txt .
# Runtime pins only; test deps are in requirements-dev.txt.
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Runtime: Canonical's chiselled Python 3.12 (no shell, no apt, no pip).
# Same Ubuntu release and /usr/bin/python3.12 as the build stage, so the venv works as-is.
FROM ubuntu/python:3.12-24.04_stable
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /venv /venv
COPY *.py ./
COPY templates ./templates

EXPOSE 8585

# Overrides the image's pebble entrypoint.
ENTRYPOINT ["/venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8585"]
