#!/bin/bash
# ── TCC RAG API — Google Cloud Run 一鍵部署腳本 ──
#
# 使用方式：
#   1. 確認已在 Secret Manager 中建立必要的 secret
#   2. 執行：bash deploy.sh
#
# 前提：
#   - 已安裝 gcloud CLI 並登入 (gcloud auth login)
#   - 已建立 GCP 專案
#   - Secret Manager 中已有：SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY、RAG_API_KEY
#   - Vertex AI API 已啟用，Cloud Run service account 已有 roles/aiplatform.user

set -e

# ============================================
# 📝 部署設定（請修改以下值）
# ============================================
PROJECT_ID="tcc-personal-project"               # GCP 專案 ID
REGION="asia-east1"                        # ← 台灣機房（延遲最低）
SERVICE_NAME="rag-api"                     # Cloud Run 服務名稱

# ============================================
# 🚀 開始部署
# ============================================
echo ""
echo "🔧 GCP 專案: $PROJECT_ID"
echo "📍 部署區域: $REGION"
echo "📦 服務名稱: $SERVICE_NAME"
echo "🔐 密鑰來源: Secret Manager"
echo ""

# 設定 GCP 專案
gcloud config set project "$PROJECT_ID"

# 啟用必要的 API（首次需要）
echo "📡 啟用 Cloud Run、Cloud Build、Secret Manager API..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# 建置 + 部署到 Cloud Run（使用 Secret Manager 掛載密鑰）
echo "🏗️  建置 Docker 映像並部署到 Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 3 \
    --set-env-vars "ENV=production" \
    --set-secrets "SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest,RAG_API_KEYS=RAG_API_KEY:latest" \
    --quiet

# 取得服務 URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format "value(status.url)")

echo ""
echo "============================================"
echo "✅ 部署成功！"
echo "============================================"
echo ""
echo "🌐 API 網址:       $SERVICE_URL"
echo "📄 API 文件:       $SERVICE_URL/docs"
echo "❤️  Health Check:  $SERVICE_URL/api/health"
echo ""
echo "測試指令："
echo "  curl $SERVICE_URL/api/health"
echo ""
