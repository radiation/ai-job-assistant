#!/bin/sh
set -eu

PROJECT="bryanchoate"
REGION="us-central1"
SERVICE="ai-job-finder"
MIGRATION_JOB="ai-job-finder-migrate"
RUNTIME_SA="ai-job-finder-runtime@bryanchoate.iam.gserviceaccount.com"
CLOUD_SQL="bryanchoate:us-central1:bryanchoate-postgres"

TAG="$(git rev-parse --short HEAD)"
IMAGE="us-central1-docker.pkg.dev/${PROJECT}/bootstrap/ai-job-finder:${TAG}"

docker buildx build \
  --platform linux/amd64 \
  -t "$IMAGE" \
  --push \
  .

gcloud run jobs deploy "$MIGRATION_JOB" \
  --project="$PROJECT" \
  --region="$REGION" \
  --image="$IMAGE" \
  --service-account="$RUNTIME_SA" \
  --set-cloudsql-instances="$CLOUD_SQL" \
  --set-env-vars="DB_USER=job_finder_app,DB_NAME=job_finder,INSTANCE_UNIX_SOCKET=/cloudsql/${CLOUD_SQL}" \
  --set-secrets="DB_PASSWORD=job-finder-db-password:latest" \
  --command="/app/.venv/bin/alembic" \
  --args="upgrade,head" \
  --max-retries=0

gcloud run jobs execute "$MIGRATION_JOB" \
  --project="$PROJECT" \
  --region="$REGION" \
  --wait

gcloud run deploy "$SERVICE" \
  --project="$PROJECT" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$RUNTIME_SA" \
  --set-cloudsql-instances="$CLOUD_SQL" \
  --set-env-vars="DB_USER=job_finder_app,DB_NAME=job_finder,INSTANCE_UNIX_SOCKET=/cloudsql/${CLOUD_SQL},ENABLE_DEV_RESET_API=false,IDENTITY_PLATFORM_PROJECT_ID=${PROJECT},IDENTITY_PLATFORM_TENANT_ID=${IDENTITY_PLATFORM_TENANT_ID:-},FIREBASE_WEB_API_KEY=${FIREBASE_WEB_API_KEY:?Set FIREBASE_WEB_API_KEY},FIREBASE_WEB_AUTH_DOMAIN=${FIREBASE_WEB_AUTH_DOMAIN:?Set FIREBASE_WEB_AUTH_DOMAIN},FIREBASE_WEB_APP_ID=${FIREBASE_WEB_APP_ID:?Set FIREBASE_WEB_APP_ID},AUTH_COOKIE_SECURE=true,CSRF_COOKIE_SECURE=true" \
  --set-secrets="DB_PASSWORD=job-finder-db-password:latest" \
  --allow-unauthenticated \
  --min=0 \
  --max=2 \
  --port=8080
