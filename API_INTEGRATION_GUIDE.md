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
| 3 | **GET** | **`/api/filters`** | **🆕 動態取得可用篩選值（分類、年度等）** |
| 4 | POST | `/api/search` | 語義搜尋（回傳 chunks） |
| 5 | POST | `/api/ask` | RAG 問答（同步） |
| 6 | POST | `/api/ask/stream` | RAG 問答（SSE 串流） |
| 7 | POST | `/api/ask/compare` | 多組比較問答（SSE 串流） |
| 8 | GET | `/api/documents` | 文件列表（分頁＋篩選） |
| 9 | POST | `/api/feedback` | 儲存使用者回饋 |

---

### 1. 健康檢查

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
    "財務報告": 12,
    "TCFD報告": 4
  },
  "source_types": {
    "pdf": 21,
    "url": 131
  }
}
```

---

### 3. 🆕 取得可用篩選值

```
GET /api/filters
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**說明**：動態從資料庫讀取目前實際入庫的所有可用篩選選項。外部 App 可用此端點建立動態下拉選單，無需硬寫分類名稱。

**推薦用法**：App 啟動時呼叫一次，快取結果供使用者選擇篩選條件。

**回應範例**：
```json
{
  "categories": ["TCFD報告", "年度報告", "永續報告書", "財務報告", "公司政策文件"],
  "fiscal_years": ["2024", "2023", "2022", "2021"],
  "languages": ["en", "zh-TW"],
  "groups": ["台泥企業團"],
  "companies": ["Molicel", "台泥", "台泥儲能"]
}
```

---

### 4. 語義搜尋

```
POST /api/search
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：
| 欄位 | 類型 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| `query` | string | ✅ | — | 自然語言查詢 |
| `top_k` | int | ❌ | 5 | 回傳最大筆數 (1-20) |
| `threshold` | float | ❌ | 0.3 | 最低相似度門檻 (0-1) |
| `use_hybrid` | bool | ❌ | true | 是否使用混合搜尋 |
| `language` | string | ❌ | null | 語言篩選（`zh-TW` / `en`），null 則不限 |
| `fiscal_year` | string | ❌ | null | 會計年度篩選（如 `"2024"`），null 則不限 |
| `category` | string | ❌ | null | **🆕 文件分類篩選**（如 `"財務報告"`、`"TCFD報告"`），null 則不限 |
| `group` | string | ❌ | `"台泥企業團"` | 集團篩選，預設台泥企業團。傳 `null` 搜全部集團 |
| `company` | string | ❌ | null | 子公司篩選，null 則不限 |

**基本搜尋**：
```json
{
  "query": "公司碳排放目標是什麼？",
  "top_k": 5
}
```

**篩選特定分類 + 年度**：
```json
{
  "query": "營收表現",
  "category": "財務報告",
  "fiscal_year": "2024"
}
```

**搜尋 TCFD 相關內容**：
```json
{
  "query": "氣候風險揭露",
  "category": "TCFD報告"
}
```

**搜尋同業（不限集團）**：
```json
{
  "query": "碳排放目標",
  "group": null
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
      "category": "永續報告書",
      "fiscal_year": "2024",
      "group": "台泥企業團",
      "company": "台泥"
    }
  ],
  "count": 5
}
```

---

### 5. AI 問答 (RAG)

```
POST /api/ask
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：
| 欄位 | 類型 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| `question` | string | ✅ | — | 使用者的問題 |
| `top_k` | int | ❌ | 5 | 參考段落數 (1-15) |
| `search_mode` | string | ❌ | `"hybrid"` | `"hybrid"`（推薦）或 `"hybrid_rerank"` |
| `history` | array | ❌ | null | 對話歷史 |
| `language` | string | ❌ | null | 語言篩選 |
| `fiscal_year` | string | ❌ | null | 會計年度篩選（如 `"2024"`），null 則不限 |
| `category` | string | ❌ | null | **🆕 文件分類篩選**（如 `"財務報告"`），null 則不限 |
| `group` | string | ❌ | `"台泥企業團"` | 集團篩選 |
| `company` | string | ❌ | null | 子公司篩選 |

**基本問答**：
```json
{
  "question": "台泥2024年的營收表現如何？",
  "top_k": 5
}
```

**限定分類問答**：
```json
{
  "question": "台泥的氣候相關財務風險有哪些？",
  "category": "TCFD報告",
  "fiscal_year": "2024"
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

### 6. AI 問答串流版 (SSE)

```
POST /api/ask/stream
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

**請求參數**：與 `/api/ask` 完全相同（含 `category`）。

> ℹ️ **集團篩選**：`group` 預設為 `"台泥企業團"`。若要搜尋同業資料，請明確傳入 `"group": null`。

**回應格式**：`text/event-stream`（Server-Sent Events），逐 token 回傳：

```
data: {"event": "sources", "sources": [...], "count": 5}

data: {"event": "token", "text": "台泥"}
data: {"event": "token", "text": "113年度"}
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
  body: JSON.stringify({
    question: "台泥碳排目標",
    category: "TCFD報告",   // 🆕 可選：限定分類
    fiscal_year: "2024",    // 可選：限定年度
  })
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

### 7. 多組比較問答 (SSE)

```
POST /api/ask/compare
Content-Type: application/json
X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy
```

AI 對多個公司或年度分別搜尋後，交叉比較並輸出 Markdown 表格。

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

### 8. 文件列表

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
      "status": "已發布",
      "created_at": "2024-03-15T08:30:00"
    }
  ],
  "count": 10,
  "total": 42
}
```

---

### 9. 使用者回饋

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

## 典型外部 App 整合流程

```
+─────────────────────────────────────────────────────+
│  App 啟動時                                          │
│  GET /api/filters  →  取得可用分類、年度、語言清單    │
│  → 建立 UI 下拉選單                                   │
+─────────────────────────────────────────────────────+
           │ 使用者選擇篩選條件後
           ▼
+─────────────────────────────────────────────────────+
│  POST /api/ask/stream                                │
│  { question, category, fiscal_year, group }          │
│  → 逐 token 顯示 AI 回答                             │
│  → 顯示引用出處                                      │
+─────────────────────────────────────────────────────+
           │ 收到回答後
           ▼
+─────────────────────────────────────────────────────+
│  POST /api/feedback                                  │
│  { question, answer, rating }                        │
+─────────────────────────────────────────────────────+
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

# 取得可用篩選值
filters = requests.get(f"{API_URL}/api/filters", headers=headers).json()
print("可用分類：", filters["categories"])
print("可用年度：", filters["fiscal_years"])

# 限定分類搜尋
response = requests.post(f"{API_URL}/api/search", headers=headers, json={
    "query": "氣候風險",
    "category": "TCFD報告",
    "fiscal_year": "2024",
    "top_k": 5,
})
print(response.json())

# AI 問答（限定分類）
response = requests.post(f"{API_URL}/api/ask", headers=headers, json={
    "question": "台泥的永續發展策略是什麼？",
    "category": "永續報告書",
})
print(response.json()["answer"])
```

### JavaScript (Node.js / 前端)

```javascript
const API_URL = "https://rag-api-1019292564477.asia-east1.run.app";
const API_KEY = "b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy";

// 取得可用篩選值
const filters = await fetch(`${API_URL}/api/filters`, {
  headers: { "X-API-Key": API_KEY },
}).then(r => r.json());
console.log("Categories:", filters.categories);
console.log("Fiscal years:", filters.fiscal_years);

// 搜尋（限定分類）
const res = await fetch(`${API_URL}/api/search`, {
  method: "POST",
  headers: { "X-API-Key": API_KEY, "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "碳排放目標",
    category: "永續報告書",
    top_k: 5,
  }),
});
const data = await res.json();
console.log(data.results);
```

### cURL

```bash
# 取得可用篩選值（🆕）
curl "https://rag-api-1019292564477.asia-east1.run.app/api/filters" \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy"

# 搜尋（限定分類 + 年度）
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/search \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"query": "氣候風險", "category": "TCFD報告", "fiscal_year": "2024"}'

# AI 問答（限定分類）
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/ask \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"question": "台泥的永續發展策略是什麼？", "category": "永續報告書"}'

# 比較問答（SSE）
curl -X POST https://rag-api-1019292564477.asia-east1.run.app/api/ask/compare \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy" \
  -H "Content-Type: application/json" \
  -d '{"question": "比較碳排強度", "groups": [{"group": "台泥企業團"}, {"group": "亞泥"}]}'

# 文件列表（篩選財務報告 2023 年）
curl "https://rag-api-1019292564477.asia-east1.run.app/api/documents?category=財務報告&fiscal_year=2023&limit=20" \
  -H "X-API-Key: b6uFgdcxPyZdujgk3SyG1NGKc6d18DLy"
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
5. `category` 篩選的可用值請透過 `/api/filters` 動態取得，避免硬寫造成不相符

---

## 多因子加權排序（自動生效）

所有搜尋結果會根據文件的 `fiscal_year` 和 `category` 自動進行多因子加權排序，**較新、較權威的文件排名更前**。此功能自動生效，不需要額外參數。

**排序公式**：
```
adjusted_score = similarity × 0.60 + year_score × 0.25 + source_weight × 0.15
```

**年份分數**（以結果集中最新年份為基準 1.0，每差一年 -0.25）：

| fiscal_year | year_score |
|-------------|:--:|
| 最新年 | 1.00 |
| 最新年 -1 | 0.75 |
| 最新年 -2 | 0.50 |
| 未填 | 0.85 |

**來源類型權重**（依 `category` 欄位）：

| category | source_weight | 理由 |
|----------|:---:|------|
| 永續報告書 | 1.00 | 最權威，ESG 核心文件 |
| 網頁 | 0.90 | 最即時，通常是最新消息 |
| 年度報告 | 0.75 | 有 ESG 章節但非主文件 |
| 其他 | 0.60 | 未分類 / 其他類型 |

> 💡 **向下相容**：現有程式不做任何修改即可自動享受加權排序的優化。

---

## 篩選參數說明

所有搜尋與問答端點支援以下篩選參數（均可組合使用）：

| 參數 | 預設值 | 行為 |
|------|--------|------|
| `category` | `null` | 不限分類（搜全部文件類型） |
| `category: "永續報告書"` | 指定值 | 只搜永續報告書 |
| `category: "TCFD報告"` | 指定值 | 只搜 TCFD 氣候報告 |
| `fiscal_year` | `null` | 不限年度 |
| `group` | `"台泥企業團"` | 只搜台泥企業團的文件 |
| `group: null` | 無篩選 | 搜尋所有集團（含同業） |
| `company` | `null` | 不限子公司 |

> ℹ️ **外部程式零修改**：現有呼叫不帶 `category` 參數，預設就是不限分類，行為不變。
