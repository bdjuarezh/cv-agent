#!/usr/bin/env bash
# NO EJECUTAR. Evidencia del ADR 0001.
# Vertex Vector Search se evaluó y descartó: el endpoint desplegado tiene un piso
# de ~$56/mes (e2-standard-2) sin escala a cero, para un corpus de 614 KB cuyo
# índice cuesta $0.0018 construir. Ver docs/adr/0001-retrieval-backend.md.
# Criterio de reversión: corpus > 10^5 vectores o requisito de multi-tenancy.
set -euo pipefail
: "${PROJECT:?}" "${REGION:?}"

gcloud ai indexes create \
  --display-name=cv-index --region="$REGION" \
  --metadata-file=infra/vector_index_metadata.json

gcloud ai index-endpoints create \
  --display-name=cv-index-endpoint --region="$REGION" --public-endpoint-enabled

# gcloud ai index-endpoints deploy-index ... --machine-type=e2-standard-2
# ^ este paso es el que empieza a cobrar por hora
