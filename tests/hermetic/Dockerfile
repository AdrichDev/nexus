FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs >/dev/null && rm -rf /var/lib/apt/lists/*
COPY requirements-hermetic.txt /req.txt
RUN pip install --no-cache-dir -r /req.txt pytest
