"""
modules/rag_chat.py — RAG 聊天核心模組
將搜尋結果與使用者問題送入 Gemini，生成含出處引用的答案。
"""
from __future__ import annotations

from typing import Any, Optional

from google import genai
from google.genai import types
from supabase import Client

from config import GEMINI_API_KEY
from modules.retriever import SemanticRetriever


class RagChat:
    """
    RAG 聊天機器人：
    1. 根據問題搜尋相關 chunks
    2. 組合 prompt（附帶搜到的資料）
    3. 呼叫 Gemini 生成答案 + 引用出處
    """

    _CHAT_MODEL = "gemini-3-flash-preview"

    _SYSTEM_PROMPT = """你是一位專業的 ESG 與財務分析助理。你的任務是根據提供的參考資料回答使用者的問題。

規則：
1. **只根據提供的參考資料回答**。如果資料中沒有足夠的資訊，請誠實告知「根據目前資料庫中的資料，無法找到相關資訊」。
2. **引用出處**：回答中引用的每項事實，都必須在句末標註來源，格式為 [來源N]。
3. **回答語言**：使用繁體中文。
4. **完整性**：盡量提供完整、有意義的回答，包含數據和具體內容。
5. **不要編造**：絕對不要捏造參考資料中沒有的內容。

回答格式範例：
台泥113年度合併營收達新台幣1,546億元，較前一年增加41.4% [來源1]。每股盈餘為1.45元 [來源1]。在永續發展方面，台泥積極推動低碳建材... [來源2]。"""

    def __init__(
        self,
        supabase_client: Client,
        api_key: Optional[str] = None,
    ) -> None:
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError("未提供 GEMINI_API_KEY")
        self._genai = genai.Client(api_key=key)
        self._retriever = SemanticRetriever(supabase_client, api_key=key)
        self._supabase = supabase_client

    def ask(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        search_mode: str = "hybrid",
        top_k: int = 5,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        RAG 問答。

        Parameters
        ----------
        question : str
            使用者的問題。
        history : list[dict] | None
            對話歷史，每個 dict 包含 role ("user"/"assistant") 和 content。
        search_mode : str
            "hybrid" 或 "hybrid_rerank"。
        top_k : int
            搜尋結果數量。
        language : str | None
            限制搜尋語言（如 "en"），None 則不限。

        Returns
        -------
        dict
            - answer: str (AI 生成的答案)
            - sources: list[dict] (引用的來源資訊)
            - search_results: list[dict] (原始搜尋結果)
        """
        # 1) 搜尋相關 chunks
        results = self._retriever.hybrid_search(question, top_k=top_k * 2, language=language)

        # 2) 如果啟用 re-ranking，精排結果
        if search_mode == "hybrid_rerank" and results:
            results = self._retriever.rerank(question, results, top_k=top_k)
        else:
            results = results[:top_k]

        if not results:
            return {
                "answer": "根據目前資料庫中的資料，無法找到與您問題相關的資訊。請嘗試更換關鍵字，或確認相關文件已入庫。",
                "sources": [],
                "search_results": [],
            }

        # 3) 組合參考資料
        context_parts = []
        sources = []
        for i, r in enumerate(results, 1):
            meta = r.get("metadata") or {}
            doc_name = r.get("display_name") or r.get("file_name", "未知文件")
            source_info = {
                "index": i,
                "document_name": doc_name,
                "file_name": r.get("file_name", ""),
                "section_title": meta.get("section_title", ""),
                "page_start": meta.get("page_start"),
                "page_end": meta.get("page_end"),
                "report_group": r.get("report_group", ""),
                "similarity": r.get("similarity", 0),
                "search_type": r.get("search_type", "vector"),
            }
            sources.append(source_info)

            # 組合 context
            page_info = ""
            if meta.get("page_start"):
                ps = meta["page_start"]
                pe = meta.get("page_end")
                page_info = f" （第{ps}{f'-{pe}' if pe and pe != ps else ''}頁）"

            context_parts.append(
                f"[來源{i}] 文件：{doc_name}{page_info}\n"
                f"章節：{meta.get('section_title', '無')}\n"
                f"內容：\n{r['text_content']}\n"
            )

        context = "\n---\n".join(context_parts)

        # 4) 組合對話訊息
        messages = [
            types.Content(
                role="user",
                parts=[types.Part(text=self._SYSTEM_PROMPT)],
            ),
            types.Content(
                role="model",
                parts=[types.Part(text="好的，我會嚴格根據提供的參考資料回答，並標註出處。")],
            ),
        ]

        # 加入對話歷史
        if history:
            for msg in history[-6:]:  # 只保留最近 6 輪
                role = "model" if msg["role"] == "assistant" else "user"
                messages.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=msg["content"])],
                    )
                )

        # 加入當前問題 + 參考資料
        user_prompt = f"""以下是從知識庫中搜尋到的參考資料：

{context}

---

使用者問題：{question}

請根據以上參考資料回答，並在引用處標註 [來源N]。"""

        messages.append(
            types.Content(
                role="user",
                parts=[types.Part(text=user_prompt)],
            )
        )

        # 5) 呼叫 Gemini 生成
        response = self._genai.models.generate_content(
            model=self._CHAT_MODEL,
            contents=messages,
        )

        answer = response.text.strip()

        return {
            "answer": answer,
            "sources": sources,
            "search_results": results,
        }
