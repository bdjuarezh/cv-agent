#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT:?}"
SA="cv-agent-sa@${PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts create cv-agent-sa \
  --display-name="CV agent runtime" || true

for role in roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA}" --role="$role" --condition=None
done
