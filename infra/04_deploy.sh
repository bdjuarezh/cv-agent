#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT:?}" "${REGION:?}"

# --min-instances=1 asume que el endpoint ya está registrado en la plataforma Banorte
# (Puerta 2, 05_GCP_ONBOARDING.md). Para el primer deploy, antes de registrar, usa 0
# (gcloud run services update cv-agent --region="$REGION" --min-instances=0) y sube a 1
# justo antes de compartir la URL — así no pagas instancias siempre activas sin necesidad.
gcloud run deploy cv-agent \
  --source . \
  --region="$REGION" \
  --service-account="cv-agent-sa@${PROJECT}.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=1 --concurrency=80 \
  --cpu=1 --memory=1Gi --cpu-boost --no-cpu-throttling \
  --timeout=300 \
  --set-env-vars="GCP_PROJECT=${PROJECT},VERTEX_REGION=us-east5,CLOUD_RUN_REGION=${REGION},ENV=prod,PROVIDER_BACKEND=anthropic_direct" \
  --set-secrets="API_KEY=cv-agent-api-key:latest,ANTHROPIC_API_KEY=cv-agent-anthropic-key:latest"
