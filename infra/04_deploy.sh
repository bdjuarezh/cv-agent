#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT:?}" "${REGION:?}"

# --min-instances=1 asume que el endpoint ya está registrado en la plataforma Banorte
# (Puerta 2, 05_GCP_ONBOARDING.md). Para el primer deploy, antes de registrar, usa 0
# (gcloud run services update cv-agent --region="$REGION" --min-instances=0) y sube a 1
# justo antes de compartir la URL — así no pagas instancias siempre activas sin necesidad.
#
# Build+push explícito a `cv-agent-repo` en vez de `--source .` (que usa el repo por defecto
# `cloud-run-source-deploy`, autocreado por gcloud) — ese repo quedó con "Container import
# failed" persistente el 2026-09-03 (Cloud Build seguía completando bien, la falla era al
# importar la imagen ya subida a Cloud Run, en cualquier región, con cualquier digest —
# aislado con `hello-world` funcionando y un repo nuevo funcionando de inmediato). No se pudo
# determinar la causa raíz del lado de Google; usar un repo sano evita el problema.
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cv-agent-repo/cv-agent:latest"
gcloud artifacts repositories describe cv-agent-repo --location="$REGION" --project="$PROJECT" \
  >/dev/null 2>&1 || \
  gcloud artifacts repositories create cv-agent-repo --repository-format=docker \
    --location="$REGION" --project="$PROJECT"
gcloud builds submit --tag="$IMAGE" --project="$PROJECT" --region="$REGION"

gcloud run deploy cv-agent \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="cv-agent-sa@${PROJECT}.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=1 --concurrency=80 \
  --cpu=1 --memory=1Gi --cpu-boost --no-cpu-throttling \
  --timeout=300 \
  --set-env-vars="GCP_PROJECT=${PROJECT},VERTEX_REGION=us-east5,CLOUD_RUN_REGION=${REGION},ENV=prod,PROVIDER_BACKEND=anthropic_direct" \
  --set-secrets="API_KEY=cv-agent-api-key:latest,ANTHROPIC_API_KEY=cv-agent-anthropic-key:latest"
