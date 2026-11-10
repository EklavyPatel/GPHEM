FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils ghostscript \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 gphem

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only application assets enter the image. No local databases or credentials.
COPY app.py serve.py ./
COPY engine ./engine
COPY services ./services
COPY web ./web
COPY templates ./templates
COPY static ./static
COPY examples ./examples
COPY migrations ./migrations
COPY scripts ./scripts
RUN mkdir -p /app/instance && chown gphem:gphem /app/instance

USER gphem
CMD ["python", "serve.py"]
