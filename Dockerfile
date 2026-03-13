# ── TCC RAG API — Cloud Run 部署用 Dockerfile ──
FROM python:3.12-slim

# 設定工作目錄
WORKDIR /app

# 只安裝 API 所需的依賴（不含 Streamlit、PyMuPDF 等管理端套件）
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# 複製應用程式
COPY config.py .
COPY api/ api/
COPY modules/__init__.py modules/
COPY modules/retriever.py modules/
COPY modules/rag_chat.py modules/

# Cloud Run 會透過 PORT 環境變數指定埠號
ENV PORT=8080

# 啟動 FastAPI
CMD exec uvicorn api.server:app --host 0.0.0.0 --port $PORT
