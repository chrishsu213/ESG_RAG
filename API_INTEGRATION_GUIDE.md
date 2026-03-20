# RAG 知識庫 API 串接指南

> 本文件提供給所有需要串接 RAG 知識庫 API 的開發人員。

---

## 基本資訊

| 項目 | 值 |
|------|-----|
| **API 基礎網址** | `https://rag-api-1019292564477.asia-east1.run.app` |
| **API 文件 (Swagger)** | `https://rag-api-1019292564477.asia-east1.run.app/docs` |
| **驗證方式** | HTTP Header `X-API-Key` |
| **API Key** | `b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy` |

> ⚠️ **請勿將 API Key 寫死在前端程式碼中**，應透過環境變數或 Secret Manager 管理。

---

## 驗證方式

所有 API 請求（除 `/api/health` 外）都需要在 HTTP Header 中帶上 API Key：

```
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

未提供或 Key 錯誤時，API 將回傳 `403 Forbidden`。

---

## 可用端點

| # | Method | Path | 說明 |
|---|--------|------|------|
| 1 | GET | `/api/health` | 健康檢查（無需認證） |
| 2 | GET | `/api/stats` | 知識庫統計 |
| 3 | POST | `/api/search` | 語義搜尋（回傳 chunks） |
| 4 | POST | `/api/ask` | RAG 問答（同步） |
| 5 | POST | `/api/ask/stream` | RAG 問答（SSE 串流） |
| 6 | POST | `/api/ask/compare` | 多組比較問答（SSE 串流） |
| 7 | GET | `/api/documents` | 文件列表（分頁＋篩選） |
| 8 | POST | `/api/feedback` | 儲存使用者回饋 |

```
GET /api/health
```

**不需要 API Key**。可用於監控服務是否正常。

**回應範例**：
```json
{
  "status": "ok",
  "service": "rag-api"
}
```

---

### 2. 知識庫統計

```
GET /api/stats
```

**回應範例**：
```json
{
  "total_documents": 152,
  "total_chunks": 3847,
  "categories": {
    "永續報告書": 5,
    "網站": 120,
    "官網": 27
  },
  "source_types": {
    "pdf": 5,
    "url": 147
  }
}
```

---

### 3. 語義搜尋

```
POST /api/search
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：
| 欄位 | 類型 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| `query` | string | ✅ | — | 自然語言查詢 |
| `top_k` | int | ❌ | 5 | 回傳最大筆數 (1-50) |
| `threshold` | float | ❌ | 0.5 | 最低相似度門檻 (0-1) |
| `use_hybrid` | bool | ❌ | true | 是否使用混合搜尋 |
| `language` | string | ❌ | null | 語言篩選 (`zh-TW` / `en`) |
| `fiscal_year` | string | ❌ | null | 會計年度篩選（如 `"2024"`），null 則不限 |
| `group` | string | ❌ | `"台泥企業團"` | 集團篩選，預設台泥企業團。傳 `null` 搜全部集團 |
| `company` | string | ❌ | null | 子公司篩選，null 則不限 |

**請求範例**：
```json
{
  "query": "公司碳排放目標是什麼？",
  "top_k": 5,
  "threshold": 0.5,
  "use_hybrid": true
}
```

**篩選特定年度**：
```json
{
  "query": "營收表現",
  "fiscal_year": "2024"
}
```

**搜尋同業資料**：
```json
{
  "query": "碳排放目標",
  "group": null
}
```

**搜尋特定子公司**：
```json
{
  "query": "儲能業務",
  "company": "台泥儲能"
}
```

**回應範例**：
```json
{
  "results": [
    {
      "text_content": "台泥集團訂定2030年碳排放減量...",
      "file_name": "2024永續報告書.pdf",
      "source_type": "pdf",
      "display_name": "2024永續報告書",
      "section_title": "碳排放管理",
      "page_start": 45,
      "page_end": 46,
      "similarity": 0.8732,
      "search_type": "vector",
      "category": "永續報告書",
      "group": "台泥企業團",
      "company": "台泥"
    }
  ],
  "count": 5
}
```

---

### 4. AI 問答 (RAG)

```
POST /api/ask
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：
| 欄位 | 類型 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| `question` | string | ✅ | — | 使用者的問題 |
| `top_k` | int | ❌ | 5 | 參考段落數 (1-20) |
| `search_mode` | string | ❌ | `"hybrid"` | `"hybrid"`（推薦）或 `"hybrid_rerank"`（使用 Ranking API） |
| `history` | array | ❌ | [] | 對話歷史 |
| `language` | string | ❌ | null | 語言篩選 |
| `fiscal_year` | string | ❌ | null | 會計年度篩選（如 `"2024"`），null 則不限 |
| `group` | string | ❌ | `"台泥企業團"` | 集團篩選，預設台泥企業團。傳 `null` 搜全部集團 |
| `company` | string | ❌ | null | 子公司篩選，null 則不限 |

**請求範例**：
```json
{
  "question": "台泥2024年的營收表現如何？",
  "top_k": 5,
  "search_mode": "hybrid"
}
```

**帶對話歷史**：
```json
{
  "question": "那碳排放呢？",
  "history": [
    {"role": "user", "content": "台泥2024年的營收表現如何？"},
    {"role": "assistant", "content": "台泥2024年合併營收達..."}
  ],
  "top_k": 5
}
```

**回應範例**：
```json
{
  "answer": "台泥113年度合併營收達新台幣1,546億元，較前一年增加41.4% [來源1]。...",
  "sources": [
    {
      "index": 1,
      "document_name": "2024年度報告",
      "section_title": "營運概況",
      "page_start": 12,
      "similarity": 0.89
    }
  ],
  "search_results_count": 5
}
```
---

### 5. AI 問答串流版 (SSE)

```
POST /api/ask/stream
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：與 `/api/ask` 完全相同。

> ℹ️ **集團篩選**：`group` 預設為 `"台泥企業團"`。若要搜尋同業資料，請明確傳入 `"group": null`。

**回應格式**：`text/event-stream`（Server-Sent Events），逐 token 回傳：

```
data: {"event": "sources", "sources": [...], "count": 5}

data: {"event": "token", "text": "台泥"}
data: {"event": "token", "text": "113年度"}
data: {"event": "token", "text": "合併營收達"}
...

data: {"event": "done"}
```

| 事件 | 說明 |
|------|------|
| `sources` | 第一個事件，包含引用來源與搜尋筆數 |
| `token` | 逐 token 的 AI 回答文字 |
| `done` | 串流結束信號 |
| `error` | 發生錯誤時回傳，包含 `detail` 欄位 |

**JavaScript 串接範例**：
```javascript
const res = await fetch(`${API_URL}/api/ask/stream`, {
  method: "POST",
  headers: { "X-API-Key": API_KEY, "Content-Type": "application/json" },
  body: JSON.stringify({ question: "台泥碳排目標" })
});

const reader = res.body.getReader();
const decoder = new TextDecoder();
let answer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const lines = decoder.decode(value).split("\n");
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const event = JSON.parse(line.slice(6));
    if (event.event === "token") {
      answer += event.text;
      // 即時更新 UI
    } else if (event.event === "done") {
      // 串流結束
    }
  }
}
```

---

### 6. 多組比較問答 (SSE)

```
POST /api/ask/compare
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

AI 對多個公司或年度分別搜尋後，交叉比較並輸出 Markdown 表格。適合「比較台泥與亞泥的碳排強度」此類問題。

**請求參數**：
| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `question` | string | ✅ | 比較問題 |
| `groups` | array | ✅ | 2~6 組篩選條件，每組可含 `group`、`company`、`fiscal_year` |
| `top_k` | int | ❌ | 每組參考段落數（預設 5） |
| `language` | string? | ❌ | 語言篩選 |
| `history` | array? | ❌ | 對話歷史 |

**請求範例**：
```json
{
  "question": "比較台泥與亞泥 2023 年的碳排放強度",
  "groups": [
    {"group": "台泥企業團", "fiscal_year": "2023"},
    {"group": "亞泥",       "fiscal_year": "2023"}
  ],
  "top_k": 5
}
```

**回應格式**：SSE 串流，與 `/api/ask/stream` 完全相同（`sources` → `token` → `done`）。

---

### 7. 文件列表

```
GET /api/documents
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**Query Parameters**：
| 參數 | 說明 | 範例 |
|------|------|------|
| `category` | 文件類別 | `永續報告書` |
| `group` | 集團 | `台泥企業團` |
| `company` | 子公司 | `台泥儲能` |
| `fiscal_year` | 年度 | `2023` |
| `source_type` | 來源類型 | `pdf` / `web` |
| `limit` | 每頁筆數（預設 50） | `20` |
| `offset` | 分頁起始（預設 0） | `40` |

**回應範例**：
```json
{
  "documents": [
    {
      "id": 101,
      "file_name": "TCC_ESG_2023.pdf",
      "display_name": "台泥 2023 永續報告書",
      "category": "永續報告書",
      "fiscal_year": "2023",
      "group": "台泥企業團",
      "source_type": "pdf",
      "status": "active",
      "created_at": "2024-03-15T08:30:00"
    }
  ],
  "count": 10,
  "total": 42
}
```

---

### 8. 使用者回饋

```
POST /api/feedback
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：
| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `question` | string | ✅ | 使用者的問題 |
| `answer` | string | ✅ | AI 回答 |
| `rating` | int | ✅ | 1~5 星評分 |
| `comment` | string? | ❌ | 文字回饋 |
| `session_id` | string? | ❌ | 外部 App 的 Session ID |
| `source` | string? | ❌ | 來源（`line_bot` / `web` / `api`） |

**請求範例**：
```json
{
  "question": "台泥的碳中和目標是什麼？",
  "answer": "根據台泥 2023 年報...",
  "rating": 5,
  "comment": "回答很完整",
  "source": "line_bot"
}
```

**回應**：
```json
{"status": "ok", "message": "回饋已儲存"}
```

---

## 各語言串接範例

### Python

```python
import requests

API_URL = "https://rag-api-1019292564477.asia-east1.run.app"
API_KEY = "b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy"

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# 搜尋
response = requests.post(f"{API_URL}/api/search", headers=headers, json={
    "query": "碳排放目標",
    "top_k": 5,
})
print(response.json())

# AI 問答
response = requests.post(f"{API_URL}/api/ask", headers=headers, json={
    "question": "台泥的永續發展策略是什麼？",
})
print(response.json()["answer"])
```

### JavaScript (Node.js / 前端)

```javascript
const API_URL = "https://rag-api-1019292564477.asia-east1.run.app";
const API_KEY = "b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy";

// 搜尋
const res = await fetch(`${API_URL}/api/search`, {
  method: "POST",
  headers: {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    query: "碳排放目標",
    top_k: 5,
  }),
});
const data = await res.json();
console.log(data.results);
```

### cURL

```bash
# 健康檢查
curl https://rag-api-1019292564477.asia-east1.run.app/api/health

# 搜尋
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/search \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"query": "碳排放目標", "top_k": 5}'

# AI 問答
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/ask \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"question": "台泥的永續發展策略是什麼？"}'

# 比較問答（SSE）
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/ask/compare \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"question": "比較碳排強度", "groups": [{"group": "台泥企業團"}, {"group": "亞泥"}]}'

# 文件列表（篩選 2023 年）
curl "https://rag-api-1019292564477.asia-east1.run.app/api/documents?fiscal_year=2023&limit=20" \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy"

# 儲存回饋
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/feedback \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"question": "碳中和目標？", "answer": "2050年...", "rating": 5}'
```

---

## 錯誤碼

| HTTP Status | 說明 | 處理方式 |
|-------------|------|---------|
| `200` | 成功 | 正常處理回應 |
| `403` | API Key 無效或未提供 | 檢查 `X-API-Key` Header |
| `500` | 伺服器內部錯誤 | 查看 `detail` 欄位取得錯誤訊息 |
| `503` | 服務未就緒 | 稍後重試 |

---

## 注意事項

1. API 部署於 Google Cloud Run（台灣 asia-east1 機房），冷啟動可能需要 3-5 秒
2. AI 問答 (`/api/ask`) 回應時間約 3-10 秒（取決於問題複雜度）
3. 搜尋 (`/api/search`) 回應時間約 1-3 秒
4. 建議呼叫端設定 timeout 至少 30 秒

---

## 多因子加權排序（自動生效）

所有搜尋結果會根據文件的 `fiscal_year` 和 `category` 自動進行多因子加權排序，**較新、較權威的文件排名更前**。此功能自動生效，不需要額外參數。

**排序公式**：
```
adjusted_score = similarity × 0.60 + year_score × 0.25 + source_weight × 0.15
```

**年份分數**（以 2026 為當年）：

| fiscal_year | year_score |
|-------------|:--:|
| 2026 | 1.00 |
| 2025 | 0.85 |
| 2024 | 0.70 |
| 2023 | 0.55 |
| 2022 | 0.40 |
| 未填 | 0.70 |

**來源類型權重**（依 `category` 欄位）：

| category | source_weight | 理由 |
|----------|:---:|------|
| 永續報告書 | 1.00 | 最權威，ESG 核心文件 |
| 網頁 | 0.90 | 最即時，通常是最新消息 |
| 年度報告 | 0.75 | 有 ESG 章節但非主文件 |
| 其他 | 0.60 | 未分類 / 其他類型 |

> 💡 **向下相容**：現有程式不做任何修改即可自動享受加權排序的優化。

---

## 集團篩選說明

所有搜尋與問答端點支援 `group` 與 `company` 篩選參數：

| 參數 | 預設值 | 行為 |
|------|--------|------|
| `group` | `"台泥企業團"` | 只搜台泥企業團的文件 |
| `group: null` | 無篩選 | 搜尋所有集團（含同業） |
| `company` | `null` | 不限子公司 |
| `company: "台泥儲能"` | 指定值 | 只搜該子公司文件 |

> ℹ️ **外部程式零修改**：現有呼叫不帶 `group` 參數，預設就是台泥企業團，行為不變。要搜同業需明確傳 `"group": null`。
