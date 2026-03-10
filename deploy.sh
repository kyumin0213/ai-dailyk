#!/usr/bin/env bash
# DailyK AI Newsroom — Cloud Run 배포 스크립트
# 사용법: ./deploy.sh
#
# 전제조건:
#   - gcloud auth login 완료
#   - ANTHROPIC_API_KEY, GEMINI_API_KEY 환경변수 설정
#   - gcloud config set project dailyk-newsroom

set -e
cd "$(dirname "$0")"

PROJECT="dailyk-newsroom"
REGION="asia-northeast3"
SERVICE="ai-dailyk-api"
IMAGE="gcr.io/${PROJECT}/${SERVICE}"

# API 키 확인
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "오류: ANTHROPIC_API_KEY 환경변수가 없습니다."
  echo "  export ANTHROPIC_API_KEY=sk-ant-..."
  exit 1
fi
if [ -z "$GEMINI_API_KEY" ]; then
  echo "오류: GEMINI_API_KEY 환경변수가 없습니다."
  echo "  export GEMINI_API_KEY=AIza..."
  exit 1
fi

echo "=== Cloud Run 배포 시작 ==="
echo "프로젝트: $PROJECT / 리전: $REGION / 서비스: $SERVICE"
echo ""

# 1. Docker 이미지 빌드 & 푸시 (Cloud Build)
echo "[1/3] Docker 이미지 빌드 중..."
gcloud builds submit \
  --tag "$IMAGE" \
  --project "$PROJECT" \
  .

# 2. Cloud Run 배포
echo ""
echo "[2/3] Cloud Run 배포 중..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 600 \
  --concurrency 4 \
  --set-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY},GEMINI_API_KEY=${GEMINI_API_KEY}" \
  --project "$PROJECT"

# 3. 서비스 URL 가져오기
echo ""
echo "[3/3] 배포 완료. URL 가져오는 중..."
CLOUD_RUN_URL=$(gcloud run services describe "$SERVICE" \
  --platform managed \
  --region "$REGION" \
  --format "value(status.url)" \
  --project "$PROJECT")

echo ""
echo "✓ Cloud Run URL: $CLOUD_RUN_URL"

# 4. app.js의 API_BASE 교체
echo ""
echo "app.js 업데이트 중..."
sed -i '' "s|'CLOUD_RUN_URL_PLACEHOLDER'|'${CLOUD_RUN_URL}'|g" app.js
echo "✓ app.js 업데이트 완료"

# 5. git 커밋 & push
echo ""
echo "git push 중 (Cloudflare Pages 자동 배포 트리거)..."
git add app.js
git commit -m "feat: Cloud Run URL 업데이트 (${CLOUD_RUN_URL})"
git push

echo ""
echo "========================================="
echo "  배포 완료!"
echo "  API    : $CLOUD_RUN_URL"
echo "  Pages  : https://ai-dailyk.pages.dev"
echo "========================================="
echo ""
echo "Cloudflare Pages 빌드가 완료되면 pages.dev에서 기사 생성 가능합니다."
