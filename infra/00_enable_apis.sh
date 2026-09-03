#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT:?}" "${REGION:?}"

gcloud config set project "$PROJECT"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com
gcloud artifacts repositories create apps \
  --repository-format=docker --location="$REGION" || true
