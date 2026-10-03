# Multi-stage build: compile the Vite/React SPA in a Node stage, then serve
# only the static dist/ output from a tiny nginx image. node_modules and the
# dev-server tooling never make it into the final image.
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite bakes VITE_* variables into the built JS at build time (not
# runtime), so they're passed as build args here. Left unset, the app falls
# back to its local-dev defaults (http://localhost:5005 etc.) which is
# exactly right for `docker compose up` when ports are published to the
# host under those same names - see docker-compose.yml and docs/DEPLOYMENT.md.
ARG VITE_RASA_WEBHOOK_URL=
ARG VITE_RASA_API_URL=
ARG VITE_ADMIN_API_URL=
ENV VITE_RASA_WEBHOOK_URL=${VITE_RASA_WEBHOOK_URL}
ENV VITE_RASA_API_URL=${VITE_RASA_API_URL}
ENV VITE_ADMIN_API_URL=${VITE_ADMIN_API_URL}

RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
