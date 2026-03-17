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
      "category": "永續報告書"
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
| `search_mode` | string | ❌ | `"hybrid"` | `"hybrid"` 或 `"hybrid_rerank"` |
| `history` | array | ❌ | [] | 對話歷史 |
| `language` | string | ❌ | null | 語言篩選 |
| `fiscal_year` | string | ❌ | null | 會計年度篩選（如 `"2024"`），null 則不限 |

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

## 時間加權排序（自動生效）

所有搜尋結果會根據文件的 `fiscal_year` 自動進行時間加權排序，**較新的文件排名更前**。此功能自動生效，不需要額外參數。

**排序公式**：
```
adjusted_score = similarity × 0.9 + year_score × 0.1
```

| fiscal_year | year_score（以 2026 為當年） |
|-------------|:--:|
| 2026 | 1.00 |
| 2025 | 0.85 |
| 2024 | 0.70 |
| 2023 | 0.55 |
| 未填 | 0.50 |
| 2022 | 0.40 |

> 💡 **向下相容**：`fiscal_year` 參數是可選的。現有程式不做任何修改即可自動享受時間加權排序的優化。只有需要精確篩選特定年份時，才需要加上 `fiscal_year` 參數。
