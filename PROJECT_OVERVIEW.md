# ESG_Parser & Cleaner — 專案總覽

## 一、專案簡介

**ESG_Parser & Cleaner** 是一套企業級的 **RAG（Retrieval-Augmented Generation）知識庫管理系統**，專為 ESG（環境、社會、治理）與投資人關係（IR）領域打造。

系統能自動將永續報告、年報、會議錄音、網頁等多種來源的非結構化資料，經過解析、清洗、切割、向量嵌入後存入 Supabase 向量資料庫，並提供語義搜尋與 AI 問答能力。

---

## 二、系統架構

```
使用者輸入（PDF / DOCX / 網頁 / 錄音檔）
   │
   ▼
┌─────────────────────────────────────────────┐
│  Admin UI (Streamlit)                       │
│  admin_ui/app.py                            │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐ │
│  │ 上傳   │ │ 文件   │ │ 檢索   │ │ AI   │ │
│  │ 匯入   │ │ 管理   │ │ 測試   │ │ 問答 │ │
│  └───┬────┘ └────────┘ └────────┘ └──────┘ │
└──────┼──────────────────────────────────────┘
       ▼
┌─────────────────────────────────────────────┐
│  處理 Pipeline (modules/)                    │
│                                              │
│  Uploader → Parser → Cleaner → Chunker       │
│         → Embedder → Exporter                │
└──────────────────────┬──────────────────────┘
                       ▼
              ┌─────────────────┐
              │   Supabase      │
              │   (pgvector)    │
              │  documents      │
              │  document_chunks│
              └────────┬────────┘
                       ▼
┌─────────────────────────────────────────────┐
│  API Server (FastAPI) — api/server.py        │
│  POST /api/search  (語義搜尋)                │
│  POST /api/ask     (RAG 問答)                │
│  GET  /api/stats   (統計)                    │
│  Deployed on: Google Cloud Run               │
└─────────────────────────────────────────────┘
```

---

## 三、核心功能

### 3.1 多格式文件解析

| 格式 | 模組 | 解析方式 |
|------|------|----------|
| PDF | `parser_pdf.py` / `parser_pdf_vision.py` | PyMuPDF 純文字 + Gemini Vision（圖表/掃描頁） |
| DOCX | `parser_docx.py` | python-docx 結構化解析 |
| 網頁 | `parser_url.py` | requests + BeautifulSoup，自動擷取標題與語言 |
| 錄音檔 | `parser_audio.py` | Gemini Audio API，支援 mp3/wav/m4a/ogg/flac/webm |

**PDF Vision 模式**提供 4 種策略：
- `text` — 純文字提取（免費）
- `auto` — 智能混合（低文字密度頁自動切換 Vision）
- `vision` — 逐頁 Vision（適合掃描件）
- `vision_pdf` — 整份 PDF 上傳（推薦，品質最佳）

### 3.2 文字清洗與切割

- **`cleaner.py`** — 自動過濾頁碼、浮水印、目錄等雜訊，正規化 Markdown
- **`chunker.py`** — 語義切割，依原文件標題層級（H1~H4）分段，保留 section metadata
- **`proofreader.py`** — AI 自動校對（修正 OCR 錯字、格式問題）

### 3.3 向量嵌入

- **`embedder.py`** — 使用 Gemini Embedding API (`gemini-embedding-001`)
- 768 維向量，支援批次嵌入
- 區分 `RETRIEVAL_DOCUMENT`（文件端）和 `RETRIEVAL_QUERY`（查詢端）

### 3.4 語義搜尋與 AI 問答

- **`retriever.py`** — 三種搜尋模式：
  - 純向量搜尋（cosine similarity）
  - 混合搜尋（向量 + 全文 RRF 融合）
  - Re-ranking（Gemini 精排）
- **`rag_chat.py`** — RAG 問答引擎：
  - 搜尋相關段落 → 組合 prompt → Gemini 生成答案
  - 強制引用出處（`[來源N]` 標記）
  - 支援多輪對話歷史
  - 拒絕編造（資料不足時誠實告知）

### 3.5 網站爬蟲

- **`crawler.py`** — 全站爬蟲，支援 BFS 搜索
- 可設定最大深度、最大頁數、排除路徑
- 支援 Sitemap XML 批次匯入

### 3.6 專有名詞字典

- 資料庫管理的術語對照表（`terms_dictionary`）
- 錄音轉錄後自動替換專有名詞
- 長詞優先策略避免誤替換

---

## 四、使用介面

### 4.1 Admin UI（Streamlit Web 後台）

**啟動方式**：`streamlit run admin_ui/app.py`

| 頁面 | 功能 |
|------|------|
| 📊 系統概況 | 文件數、Chunk 數、向量模型狀態 |
| 📤 上傳與匯入 | PDF/DOCX 上傳、網頁爬蟲、錄音檔轉錄 |
| 🗃️ 文件管理 | inline 編輯元資料（分類/語言/狀態/機密等級）、刪除、Chunk 預覽 |
| 📖 專有名詞字典 | 管理術語替換規則 |
| 🔍 檢索測試 | 即時搜尋知識庫，驗證結果品質 |
| 💬 AI 問答 | 與知識庫對話，自動附引用出處 |

具備**密碼保護**（`ADMIN_PASSWORD`），部署環境下需登入。

### 4.2 RESTful API（FastAPI）

**啟動方式**：`uvicorn api.server:app --host 0.0.0.0 --port 8000`  
**部署位置**：Google Cloud Run

| 端點 | 方法 | 功能 |
|------|------|------|
| `/api/health` | GET | 健康檢查 |
| `/api/stats` | GET | 知識庫統計（文件數、Chunk 數、分類分佈） |
| `/api/search` | POST | 語義搜尋（支援混合搜尋、語言過濾） |
| `/api/ask` | POST | RAG 問答（AI 生成答案 + 引用） |

支援 **API Key 驗證**（`X-API-Key` header），CORS 已啟用。

### 4.3 CLI 工具

- `main.py` — 命令列批次匯入文件
- `search.py` — 命令列搜尋測試
- `scripts/auto_crawl.py` — 定時爬蟲腳本

---

## 五、使用情境

### 情境 1：永續報告入庫
> 將 200 頁 PDF 永續報告拆章節上傳 → Vision 模式解析圖表 → AI 校對 → 向量嵌入 → 入庫。  
> 填寫「所屬報告」欄位，將多個章節歸為同一份報告。

### 情境 2：法說會錄音轉逐字稿
> 上傳 mp3 法說會錄音 → Gemini 自動轉錄並辨識講者 → 套用專有名詞字典修正公司/人名 → 審校後直接入庫。

### 情境 3：官網內容批次匯入
> 輸入 Sitemap URL → 自動解析所有頁面 → 批次爬取、清洗、嵌入、入庫。  
> 或使用全站爬蟲，設定深度和排除路徑。

### 情境 4：IR 平台整合
> 公司官網的 IR 頁面透過 API (`POST /api/ask`) 串接知識庫，  
> 讓投資人直接用自然語言提問：「台泥去年碳排量減少多少？」  
> AI 從永續報告中找到答案並附上出處。

### 情境 5：內部知識管理
> 同仁透過 Admin UI 的「AI 問答」功能，  
> 查詢公司政策、歷年報告數據、會議決議等，  
> 無需手動翻閱大量文件。

---

## 六、技術棧

| 層面 | 技術 |
|------|------|
| AI 模型 | Google Gemini（gemini-3-flash-preview / gemini-embedding-001） |
| 向量資料庫 | Supabase (PostgreSQL + pgvector + HNSW 索引) |
| 搜尋 | 向量相似度 + tsvector 全文檢索 + RRF 融合 |
| 後台 UI | Streamlit |
| API Server | FastAPI + Uvicorn |
| 部署 | Google Cloud Run（Docker 容器） |
| PDF 解析 | PyMuPDF + Gemini Vision |
| Secret 管理 | GCP Secret Manager / Streamlit Secrets / .env |

---

## 七、資料庫結構

### `documents` 表
| 欄位 | 說明 |
|------|------|
| `file_name` | 原始檔名 / URL |
| `file_hash` | SHA-256 去重複 |
| `source_type` | pdf / docx / url / audio |
| `category` | 分類（ESG專區/年報/會議紀錄…） |
| `display_name` | 顯示名稱 |
| `report_group` | 所屬報告（多章節歸組） |
| `language` | 語言代碼 |
| `status` | 已發布 / 已審校 / 草稿 |
| `confidentiality` | 公開 / 內部 / 機密 |

### `document_chunks` 表
| 欄位 | 說明 |
|------|------|
| `document_id` | 關聯文件 |
| `chunk_index` | 段落序號 |
| `text_content` | 純文字內容 |
| `embedding` | 768 維向量 (vector) |
| `metadata` | JSON（section_title, page_start, page_end…） |
| `fts` | tsvector 全文索引 |

### `terms_dictionary` 表
| 欄位 | 說明 |
|------|------|
| `term` | 需替換的詞彙 |
| `full_name` | 完整名稱 |

---

## 八、環境變數

| 變數名 | 用途 |
|--------|------|
| `SUPABASE_URL` | Supabase 專案 URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role Key |
| `GEMINI_API_KEY` | Google Gemini API Key |
| `ADMIN_PASSWORD` | Admin UI 登入密碼 |
| `RAG_API_KEYS` | API Server 允許的 Key 列表（逗號分隔） |

---

## 九、檔案結構

```
ESG_Parser & Cleaner/
├── admin_ui/
│   └── app.py              # Streamlit 管理後台（1125 行）
├── api/
│   ├── __init__.py
│   └── server.py            # FastAPI RESTful API
├── modules/
│   ├── chunker.py           # 語義切割
│   ├── cleaner.py           # Markdown 清洗
│   ├── crawler.py           # 全站爬蟲
│   ├── embedder.py          # Gemini 向量嵌入
│   ├── exporter.py          # Supabase 寫入
│   ├── parser_audio.py      # 錄音檔轉錄
│   ├── parser_docx.py       # DOCX 解析
│   ├── parser_pdf.py        # PDF 純文字解析
│   ├── parser_pdf_vision.py # PDF Vision 解析
│   ├── parser_url.py        # 網頁解析
│   ├── proofreader.py       # AI 校對
│   ├── rag_chat.py          # RAG 問答引擎
│   ├── retriever.py         # 語義搜尋 / 混合搜尋
│   └── uploader.py          # 檔案上傳與去重複
├── scripts/
│   └── auto_crawl.py        # 定時爬蟲腳本
├── sql/
│   ├── schema.sql           # 資料庫 schema
│   └── migrations/          # 資料庫遷移腳本（001~006）
├── config.py                # 全域設定與 Secret 讀取
├── main.py                  # CLI 批次匯入
├── search.py                # CLI 搜尋測試
├── api.py                   # 舊版 API（已由 api/server.py 取代）
├── Dockerfile               # Cloud Run 容器設定
├── deploy.sh                # Cloud Run 部署腳本
├── requirements.txt         # Streamlit 依賴
└── requirements-api.txt     # API Server 依賴
```
