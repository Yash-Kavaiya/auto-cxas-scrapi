#!/usr/bin/env bash
set -euo pipefail

echo "==> Google Cloud setup for auto-cxas-scrapi"

PROJECT=${GOOGLE_CLOUD_PROJECT:-""}
if [ -z "$PROJECT" ]; then
  read -rp "Enter your GCP Project ID: " PROJECT
fi

echo "Project: $PROJECT"
gcloud config set project "$PROJECT"

# Cloud Shell already has ADC via the Compute Engine service account.
# Only run the interactive login flow outside Cloud Shell.
if [ "${CLOUD_SHELL:-false}" = "true" ]; then
  echo "==> Running in Cloud Shell — skipping 'gcloud auth application-default login'"
  echo "    (VM service account credentials are used automatically)"
else
  gcloud auth application-default login
  gcloud auth login
fi

echo ""
echo "==> Installing auto-cxas-scrapi package..."
pip install -e ".[anthropic]" --quiet

echo ""
echo "==> Verifying cxas-scrapi connectivity..."
python -c "
from cxas_scrapi import Apps
a = Apps(project_id='$PROJECT', location='global')
apps = a.list_apps()
print(f'Found {len(apps)} apps in project.')
" || echo "[WARN] cxas-scrapi connectivity check failed -- check credentials."

echo ""
echo "==> Verifying auto-cxas CLI..."
auto-cxas --help > /dev/null && echo "auto-cxas CLI: OK" || echo "[WARN] auto-cxas CLI not found"

echo "==> Setup complete. Run: auto-cxas init"
