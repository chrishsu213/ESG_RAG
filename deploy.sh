#!/bin/bash
# ── TCC RAG API — Google Cloud Run 一鍵部署腳本 ──
#
# 使用方式：
#   1. 先設定下方的環境變數（或確認 .env 檔案已正確設定）
#   2. 執行：bash deploy.sh
#
# 前提：
#   - 已安裝 gcloud CLI 並登入 (gcloud auth login)
#   - 已建立 GCP 專案

set -e

# ============================================
# 📝 部署設定（請修改以下值）
# ============================================
PROJECT_ID="tcc-rag-project"               # GCP 專案 ID
REGION="asia-east1"                        # ← 台灣機房（延遲最低）
SERVICE_NAME="rag-api"                     # Cloud Run 服務名稱

# 環境變數（從 .env 讀取，或直接填入）
if [ -f .env ]; then
    echo "📖 從 .env 讀取環境變數..."
    export $(grep -v '^#' .env | xargs)
fi

# 確認必要的環境變數
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_SERVICE_ROLE_KEY" ] || [ -z "$GEMINI_API_KEY" ]; then
    echo "❌ 缺少必要的環境變數。請確認 .env 檔案包含："
    echo "   SUPABASE_URL=..."
    echo "   SUPABASE_SERVICE_ROLE_KEY=..."
    echo "   GEMINI_API_KEY=..."
    exit 1
fi

# ============================================
# 🚀 開始部署
# ============================================
echo ""
echo "🔧 GCP 專案: $PROJECT_ID"
echo "📍 部署區域: $REGION"
echo "📦 服務名稱: $SERVICE_NAME"
echo ""

# 設定 GCP 專案
gcloud config set project "$PROJECT_ID"

# 啟用必要的 API（首次需要）
echo "📡 啟用 Cloud Run 和 Cloud Build API..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

# 建置 + 部署到 Cloud Run
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
    --set-env-vars "SUPABASE_URL=$SUPABASE_URL,SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY,GEMINI_API_KEY=$GEMINI_API_KEY" \
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
