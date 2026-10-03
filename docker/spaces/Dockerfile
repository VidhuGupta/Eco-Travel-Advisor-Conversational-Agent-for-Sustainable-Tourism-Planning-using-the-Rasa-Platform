# Single-container bundle for HuggingFace Spaces (Docker SDK).
#
# HF Spaces' free/Docker-SDK tier publishes exactly one port for the whole
# Space, so the four services that docker-compose.yml runs as separate
# containers (rasa, actions, admin, frontend) are combined here into one
# image, started by start.sh, and fronted by a single nginx instance on
# port 7860 that reverse-proxies to each process on localhost. See
# docs/DEPLOYMENT.md's HuggingFace Spaces walkthrough for how to point a Space
# at this file (its path is NOT the repo-root Dockerfile).
#
# Build context is the repository root, e.g.:
#   docker build -f docker/spaces/Dockerfile -t terra-spaces .

# ---- frontend build -------------------------------------------------------
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin, relative API paths: nginx (this image's front door) proxies
# them to the right internal process - see nginx.conf. This is the one
# thing that differs from the docker-compose build, where each service has
# its own published host port instead.
ENV VITE_RASA_WEBHOOK_URL=/webhooks/rest/webhook
ENV VITE_RASA_API_URL=""
ENV VITE_ADMIN_API_URL=/api/admin
RUN npm run build

# ---- python deps + trained model ------------------------------------------
FROM python:3.10-slim AS backend
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl nginx \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY domain.yml config.yml credentials.yml endpoints.yml endpoints.spaces.yml ./
COPY data/ data/
COPY actions/ actions/
COPY admin_server.py .
RUN rasa train --fixed-model-name terra-model --out models

# ---- final image ------------------------------------------------------
FROM backend AS final
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
# Debian's nginx package's main nginx.conf includes both conf.d/*.conf and
# sites-enabled/*; dropping our server block in conf.d is enough - it adds
# a second (higher-numbered) port 7860 server without needing to touch or
# remove the package's unrelated default site on port 80.
COPY docker/spaces/nginx.conf /etc/nginx/conf.d/spaces.conf
COPY docker/spaces/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# HuggingFace Spaces (Docker SDK) expects the container to listen on 7860
# by default; docs/DEPLOYMENT.md shows how to set `app_port` if you change this.
EXPOSE 7860
CMD ["/app/start.sh"]
