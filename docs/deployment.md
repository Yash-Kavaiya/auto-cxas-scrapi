# Deployment

## Local development

### Prerequisites

- Python 3.11+
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) authenticated
- A live CXAS app with at least one agent

### Setup

```bash
# Clone and install
git clone https://github.com/yash-kavaiya/auto-cxas-scrapi
cd auto-cxas-scrapi
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Authenticate
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# Configure
cp .env.example .env
# Edit .env — at minimum set GOOGLE_CLOUD_PROJECT and AUTO_CXAS_APP_NAME

# Validate
python evaluate.py --dry-run
```

### Running the loop

```bash
# Dry-run (no live CXAS API calls)
python auto_loop.py --ema --dry-run --max-experiments 20

# Live, manual approval mode (prompt before keeping each improvement)
python auto_loop.py --ema --max-experiments 50

# Live, fully autonomous
AUTO_CXAS_APPROVAL_MODE=auto python auto_loop.py --ema --max-experiments 200

# With HTML report and GCS upload on completion
AUTO_CXAS_GENERATE_HTML_REPORT=true \
AUTO_CXAS_GCS_RESULTS_BUCKET=my-bucket \
python auto_loop.py --ema --max-experiments 200
```

---

## Docker

The included `Dockerfile` creates a minimal production image using a
multi-stage build:

```
Stage 1 (builder): installs pyproject.toml, builds wheel
Stage 2 (runtime): python:3.11-slim + wheel only, runs as non-root appuser
```

### Build

```bash
docker build -t auto-cxas-scrapi .
```

### Run locally with Docker

```bash
docker run --rm \
  --env-file .env \
  -v $(pwd)/results.tsv:/app/results.tsv \
  -v $(pwd)/.auto-cxas:/app/.auto-cxas \
  auto-cxas-scrapi \
  python auto_loop.py --ema --max-experiments 50
```

### Push to Artifact Registry

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev

docker tag auto-cxas-scrapi \
  us-central1-docker.pkg.dev/PROJECT_ID/my-repo/auto-cxas-scrapi:latest

docker push \
  us-central1-docker.pkg.dev/PROJECT_ID/my-repo/auto-cxas-scrapi:latest
```

---

## Cloud Run Job

Cloud Run Jobs are the recommended production deployment: they run until
completion (up to 24 h), support Secret Manager for credentials, and
automatically retry on failure.

### Architecture

```mermaid
flowchart LR
    SM[Secret Manager\ncredentials] --> JOB
    subgraph JOB["Cloud Run Job"]
        LOOP[auto_loop.py\n--ema --max-experiments 200]
    end
    JOB --> CXAS[(CXAS API)]
    JOB --> GCS[(GCS bucket\nresults.tsv)]
    JOB --> VOL[/tmp/reports\nemptyDir]
```

### Step-by-step

**1. Create secrets**

```bash
echo -n "projects/PROJECT_ID/locations/us/apps/APP_NAME" | \
  gcloud secrets create auto-cxas-app-name --data-file=-

echo -n "my-gcs-bucket" | \
  gcloud secrets create auto-cxas-gcs-bucket --data-file=-
```

**2. Build and push the image**

```bash
docker build -t gcr.io/PROJECT_ID/auto-cxas-scrapi .
docker push gcr.io/PROJECT_ID/auto-cxas-scrapi
```

**3. Edit `cloudrun.yaml`**

Replace all `PROJECT_ID` placeholders:
```bash
sed -i 's/PROJECT_ID/my-actual-project/g' cloudrun.yaml
```

**4. Deploy the job**

```bash
gcloud run jobs replace cloudrun.yaml --region=us-central1
```

**5. Execute**

```bash
# One-off execution
gcloud run jobs execute auto-cxas-scrapi --region=us-central1

# Schedule (e.g. nightly at 02:00)
gcloud scheduler jobs create http auto-cxas-nightly \
  --schedule="0 2 * * *" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT_ID/jobs/auto-cxas-scrapi:run" \
  --oauth-service-account-email=auto-cxas-scrapi@PROJECT_ID.iam.gserviceaccount.com
```

### cloudrun.yaml reference

```yaml
apiVersion: run.googleapis.com/v1
kind: Job
metadata:
  name: auto-cxas-scrapi
spec:
  template:
    spec:
      timeoutSeconds: 86400      # 24-hour max
      containers:
        - image: gcr.io/PROJECT_ID/auto-cxas-scrapi:latest
          args: ["python", "auto_loop.py", "--ema", "--max-experiments", "200"]
          resources:
            limits:
              cpu: "2"
              memory: "4Gi"
          env:
            - name: AUTO_CXAS_APP_NAME
              valueFrom:
                secretKeyRef:
                  name: auto-cxas-app-name
                  key: latest
```

### IAM requirements

The Cloud Run service account needs:

| Role | Purpose |
|---|---|
| `roles/dialogflow.admin` | CXAS API read/write |
| `roles/storage.objectCreator` | Upload results to GCS |
| `roles/secretmanager.secretAccessor` | Read secrets |

```bash
SA=auto-cxas-scrapi@PROJECT_ID.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/dialogflow.admin"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectCreator"
```

---

## CI/CD

The `.github/workflows/ci.yml` runs on every push to `main` and on all PRs:

| Job | Checks |
|---|---|
| `lint-and-test` | ruff, pyright, weight-sum assertion, 54-test count, evaluate.py --dry-run, pytest |
| `score-regression` | eval_score ≥ 0.50 gate (dry-run) |

Both jobs must pass before a PR can merge.
