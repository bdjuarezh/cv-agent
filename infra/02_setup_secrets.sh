#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT:?}"
SA="cv-agent-sa@${PROJECT}.iam.gserviceaccount.com"

KEY=$(openssl rand -hex 32)
printf '%s' "$KEY" | gcloud secrets create cv-agent-api-key --data-file=- || \
  printf '%s' "$KEY" | gcloud secrets versions add cv-agent-api-key --data-file=-

gcloud secrets add-iam-policy-binding cv-agent-api-key \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor

echo "API key (registrar en la plataforma): $KEY"
