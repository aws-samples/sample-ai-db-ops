# syntax=docker/dockerfile:1
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ---------------------------------------------------------------------------
# Agentic DB Ops — demo container.
#
# Single image that runs the Next.js front end AND the Python backend the API
# routes shell out to (callPython / resolve-admin). This preserves the real
# architecture so the hosted demo behaves exactly like local dev.
#
# Demo mode is opt-in. Running the container with ADMIN_DEV_BYPASS=1 makes the
# Change Feed + DBA Knowledge Graph read an in-process seeded store (no Neptune
# or live database needed) AND treats every signed-in user as an admin. It is
# not set here, so the image enforces the dbops-admins check by default. Set it
# only for a single-user demo on seeded data, never on a shared deployment.
# ---------------------------------------------------------------------------

# ---- Stage 1: build the Next.js production bundle -------------------------
# Base images are pulled from Amazon ECR Public (an internal-approved registry)
# rather than Docker Hub, per BuilderHub container-repo guidelines.
FROM public.ecr.aws/docker/library/node:20-bookworm-slim AS ui-build
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# ---- Stage 2: runtime (Node + Python venv + repo source) ------------------
FROM public.ecr.aws/docker/library/node:20-bookworm-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    PORT=3001 \
    PYTHON_BIN=/app/.venv/bin/python3 \
    ADMIN_OPS_CONFIG_PATH=/app/config.demo.yaml \
    CHANGEFEED_DEV_STATE_FILE=/app/src/admin_ops/changefeed/data/demo_seed.json \
    NEXT_PUBLIC_USER_ID=demo-user \
    AWS_REGION=us-east-1

# Python runtime for the callPython bridge.
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Python deps in an isolated venv that PYTHON_BIN points at.
RUN python3 -m venv /app/.venv
COPY requirements-demo.txt /app/requirements-demo.txt
RUN /app/.venv/bin/pip install --no-cache-dir -r /app/requirements-demo.txt

# Backend source + config the Python bridge imports at runtime.
COPY src/ /app/src/
COPY config.demo.yaml /app/config.demo.yaml

# Built UI (with its production deps). next start runs from /app/ui so the
# bridge's repo-root resolution (cwd without trailing /ui) lands on /app.
COPY --from=ui-build /app/ui /app/ui

# Run as the image's built-in non-root 'node' user (uid 1000) instead of root
# (CKV_DOCKER_3). Hand ownership of the app tree — including the Python venv —
# to that user so the runtime and the callPython bridge can read/execute it.
RUN chown -R node:node /app
USER node

WORKDIR /app/ui
EXPOSE 3001

# Container health probe (CKV_DOCKER_2). Node 20 ships a global fetch(); the
# Next.js server answers on $PORT (3001). Exit non-zero if it is not serving.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3001/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npm", "run", "start"]
