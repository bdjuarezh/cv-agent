#!/usr/bin/env bash
# Fase de cierre (D12): despliegue manual durante desarrollo, CI/WIF al final.
# Escrito y listo para cuando el repo esté en GitHub — no se corre todavía.
set -euo pipefail
: "${PROJECT:?}" "${REPO:?}"   # REPO = usuario/cv-agent
PN=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')

gcloud iam workload-identity-pools create gh --location=global || true
gcloud iam workload-identity-pools providers create-oidc gh \
  --location=global --workload-identity-pool=gh \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '${REPO}'"

gcloud iam service-accounts create deployer --display-name="GitHub Actions" || true
DEP="deployer@${PROJECT}.iam.gserviceaccount.com"

for role in roles/run.admin roles/iam.serviceAccountUser roles/artifactregistry.writer roles/cloudbuild.builds.editor; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${DEP}" --role="$role" --condition=None
done

gcloud iam service-accounts add-iam-policy-binding "$DEP" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PN}/locations/global/workloadIdentityPools/gh/attribute.repository/${REPO}"

echo "provider: projects/${PN}/locations/global/workloadIdentityPools/gh/providers/gh"
