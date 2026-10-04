FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs >/dev/null && rm -rf /var/lib/apt/lists/*
COPY requirements-hermetic.txt /req.txt
RUN pip install --no-cache-dir -r /req.txt pytest
# Run as an unprivileged user (Trivy DS-0002). /work and /tmp are tmpfs mounted
# at run time with uid=10001 (see run.sh).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hermetic
USER 10001
