#!/usr/bin/env bash
# Launches all three backend processes in the background and nginx in the
# foreground (so the container's main process, and the one Docker/HF Spaces
# health-checks and keeps alive, is nginx on the publicly exposed port).
set -euo pipefail
cd /app

if [ -z "${ADMIN_TOKEN:-}" ]; then
  echo "WARNING: ADMIN_TOKEN is not set - the admin dashboard will refuse" >&2
  echo "all logins until you configure it as a Space secret. The rest of" >&2
  echo "the app (traveler chat) still works." >&2
fi

echo "Starting action server on :5055..."
rasa run actions --port 5055 &

echo "Starting Rasa server on :5005..."
rasa run --enable-api --cors "*" --endpoints endpoints.spaces.yml --port 5005 &

echo "Starting admin server on :8060..."
python admin_server.py &

# Give the backends a moment to bind before nginx starts proxying to them;
# nginx will still 502 briefly on cold start if a request lands before this
# point, which is an acceptable, documented tradeoff for a demo deployment.
sleep 5

echo "Starting nginx on :7860..."
exec nginx -g "daemon off;"
