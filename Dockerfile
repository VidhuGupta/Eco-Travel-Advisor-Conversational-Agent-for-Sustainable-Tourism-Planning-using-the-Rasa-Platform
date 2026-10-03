# Multi-stage/multi-target Dockerfile for the two heavy, Python-dependency
# Rasa processes: the Rasa server (NLU/Core + REST API) and the action
# server (custom Python code in actions/). They are built from one shared
# `deps` stage so the large pip install (rasa, tensorflow, etc. - see
# requirements.txt) is cached and identical for both, but they run as two
# separate containers/services (see docker-compose.yml), matching how Rasa
# expects them to run as independent long-lived processes.
#
# Build a specific target with:
#   docker build --target rasa    -t terra-rasa    .
#   docker build --target actions -t terra-actions .
# (docker-compose.yml does this automatically via `target:`.)

# ---------------------------------------------------------------------------
# Shared dependency layer
# ---------------------------------------------------------------------------
FROM python:3.10-slim AS deps
WORKDIR /app

# build-essential is needed to build a couple of pinned wheels (e.g.
# python-crfsuite) that don't ship manylinux wheels for every platform.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Shared project files (everything both the Rasa server and the trainer
# stage need: domain, pipeline config, NLU/story/rule data, endpoints).
# ---------------------------------------------------------------------------
FROM deps AS project
COPY domain.yml config.yml credentials.yml endpoints.yml endpoints.docker.yml ./
COPY data/ data/

# ---------------------------------------------------------------------------
# Trainer: bakes a fresh model into the image at build time. This is the
# default so the image is self-contained and reproducible for platforms
# with no persistent volume (e.g. HuggingFace Spaces). docker-compose.yml
# overrides this with a bind mount of the repo's own ./models directory for
# local development, so this training step is skipped on every `compose up`
# (see docs/DEPLOYMENT.md, "Why bake the model in vs. mount it").
# ---------------------------------------------------------------------------
FROM project AS trainer
RUN rasa train --fixed-model-name terra-model --out models

# ---------------------------------------------------------------------------
# rasa: the Rasa server (NLU + Core + REST/webhook API), port 5005.
# ---------------------------------------------------------------------------
FROM project AS rasa
COPY --from=trainer /app/models /app/models
EXPOSE 5005
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fs http://127.0.0.1:5005/status || exit 1
CMD ["rasa", "run", "--enable-api", "--cors", "*", "--endpoints", "endpoints.docker.yml", "--port", "5005"]

# ---------------------------------------------------------------------------
# actions: the custom action server, port 5055. Doesn't need a trained
# model or training data, only the Python source and its own deps (which
# come from the same shared requirements.txt for guaranteed compatibility
# with the rasa-sdk version pinned there).
# ---------------------------------------------------------------------------
FROM deps AS actions
COPY actions/ actions/
EXPOSE 5055
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fs http://127.0.0.1:5055/health || exit 1
CMD ["rasa", "run", "actions", "--port", "5055"]
