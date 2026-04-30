#!/usr/bin/env bash
set -euo pipefail

echo "==> Google Cloud setup for auto-cxas-scrapi"

PROJECT=${GOOGLE_CLOUD_PROJECT:-""}
if [ -z "$PROJECT" ]; then
  read -p "Enter your GCP Project ID: " PROJECT
fi

echo "Project: $PROJECT"
gcloud config set project "$PROJECT"
gcloud auth application-default login
gcloud auth login

echo ""
echo "==> Verifying cxas-scrapi connectivity..."
python -c "
from cxas_scrapi import Apps
a = Apps(project_id='$PROJECT', location='global')
apps = a.list_apps()
print(f'Found {len(apps)} apps in project.')
" || echo "[WARN] cxas-scrapi connectivity check failed -- check credentials."

echo "==> Setup complete."
