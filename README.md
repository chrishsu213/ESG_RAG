# TCC 泛用型 RAG 知識庫

將公司文件（PDF / DOCX / 網頁）自動解析、清洗、切割、向量化，並存入 Supabase + pgvector，提供語義搜尋 API 供 IR Database 及組內其他系統串接。

## 架構

```
raw_data/          ← 放入待處理文件
modules/
  uploader.py      ← SHA-256 去重
  parser_pdf.py    ← PDF → Markdown (PyMuPDF)
  parser_docx.py   ← DOCX → Markdown (python-docx)
  parser_url.py    ← URL → Markdown (BeautifulSoup)
  cleaner.py       ← 頁首/頁尾/頁碼過濾
  chunker.py       ← 基於標題的語義切割
  embedder.py      ← Gemini text-embedding-004 向量化
  retriever.py     ← Supabase RPC 語義搜尋
  exporter.py      ← 寫入 Supabase (含 embedding)
main.py            ← CLI Pipeline 入口
search.py          ← CLI 語義搜尋工具
api.py             ← FastAPI REST 服務
```

## 安裝

```bash
pip install -r requirements.txt
```

## 環境變數

在 `.env` 中填入：

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
GEMINI_API_KEY=your-gemini-api-key
```

## Supabase 設定

在 Supabase Dashboard → SQL Editor 中執行 `sql/schema.sql`，會自動建立：
- `documents` 和 `document_chunks` 表
- `pgvector` 擴充與 HNSW 索引
- `match_chunks()` 語義搜尋 RPC 函式

## 使用方式

### 1️⃣ CLI — 匯入文件

```bash
# 匯入 PDF（含向量嵌入）
python main.py --source ./raw_data/report.pdf

# 匯入 DOCX
python main.py --source ./raw_data/policy.docx

# 匯入網頁
python main.py --source https://example.com/article

# 僅匯入純文字（不嵌入）
python main.py --source ./raw_data/report.pdf --no-embed
```

### 2️⃣ CLI — 語義搜尋

```bash
python search.py --query "公司碳排放目標" --top_k 5
python search.py --query "董事會結構" --threshold 0.6
```

### 3️⃣ REST API — 供團隊串接

```bash
# 啟動服務
python api.py
# 或：uvicorn api:app --reload --port 8000
```

**匯入文件：**
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "./raw_data/report.pdf"}'
```

**語義搜尋：**
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "碳排放", "top_k": 5}'
```

**API 文件：** 啟動後前往 `http://localhost:8000/docs` 查看完整 Swagger UI。

### 4️⃣ Admin UI — 前端管理介面

我們提供了一個基於 Streamlit 的圖形化管理後台，供非技術人員方便使用：

```bash
streamlit run admin_ui/app.py
```
啟動後會自動開啟瀏覽器，包含以下功能：
- **系統概況**：檢視資料庫總文件與段落數。
- **文件管理**：支援從本地上傳文件、輸入 URL 自動網頁抓取，以及列表與單筆文件刪除。
- **檢索測試**：視覺化介面供自由測試向量搜尋，可調整門檻並預覽 Chunk 原始文字及相似度。
