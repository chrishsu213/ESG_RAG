"""
config.py — 讀取環境變數與全域常數

支援兩種來源（優先順序）：
  1. Streamlit Cloud secrets (st.secrets) — 透過 _get_secret() 即時讀取
  2. 環境變數 / .env 檔案

注意：SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY 使用
     延遲載入（lazy-loading），確保在 Streamlit Cloud 上
     st.secrets 於首次存取時已經就緒。

Vertex AI 認證：Cloud Run 使用 ADC（compute service account），
     Streamlit Cloud 使用 GCP_SERVICE_ACCOUNT secrets，
     本機開發需 gcloud auth application-default login。
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_secret(key: str, default: str = "") -> str:
    """先從 Streamlit secrets 取值，再從環境變數取值。每次呼叫都即時讀取。"""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# ── LangSmith 設定：從 st.secrets 同步到 os.environ ──
# langsmith 套件直接讀取 os.environ，Streamlit secrets 需手動同步
for _ls_key in ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT"):
    _val = _get_secret(_ls_key)
    if _val and _ls_key not in os.environ:
        os.environ[_ls_key] = _val


# ── 延遲載入密鑰 ──────────────────────────────────────
# 各模組 import 時不會立即解析密鑰值，而是在首次存取時才呼叫 _get_secret()。
# 這確保 Streamlit Cloud 的 st.secrets 在讀取時已準備好。
_SECRET_KEYS = {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"}
_resolved_secrets: dict[str, str] = {}


def __getattr__(name: str) -> str:
    """Module-level __getattr__：延遲載入密鑰。
    當其他模組執行 `from config import SUPABASE_URL` 時，
    Python 會呼叫此函式來取得值（僅在模組層級找不到時）。
    """
    if name in _SECRET_KEYS:
        if name not in _resolved_secrets:
            _resolved_secrets[name] = _get_secret(name)
        return _resolved_secrets[name]
    raise AttributeError(f"module 'config' has no attribute {name!r}")


# ── Monkey Patch Supabase JWT Check ───────────────────
# 因應 Supabase 推出新的 Token 格式 (sb_secret_... / sb_publishable_...)
# 但 supabase-py 舊版仍會強制死扣 JWT 格式 (eyJ...)，導致拋出 Invalid API key
# 此處覆寫驗證邏輯避免報錯。新版 supabase-py 已不需要此 patch。
try:
    import supabase._sync.client as sc
    from supabase._sync.client import SyncClient

    if hasattr(sc, "is_valid_jwt"):
        sc.is_valid_jwt = lambda key: True

    # 強制覆寫 SyncClient.__init__ 繞過內部第二層檢查
    _original_init = SyncClient.__init__
    def _patched_init(self, supabase_url, supabase_key, options, **kwargs):
        placeholder = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.x"
        _original_init(self, supabase_url, placeholder, options, **kwargs)
        self.supabase_key = supabase_key
        
        # 覆寫 headers
        headers_to_update = {
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}'
        }
        self.options.headers.update(headers_to_update)
        self.auth._headers.update(headers_to_update)
        self.postgrest.session.headers.update(headers_to_update)

    SyncClient.__init__ = _patched_init
except (ImportError, AttributeError):
    # 新版 supabase-py 結構不同，不需要 monkey patch
    pass

# ── Embedding 設定 ────────────────────────────────────
EMBEDDING_MODEL: str = "gemini-embedding-001"    # Google Gemini 嵌入模型
EMBEDDING_DIMENSION: int = 768                   # 向量維度 (HNSW 上限 2000，故指定 768)

# ── Chunker 設定 ──────────────────────────────────────
CHUNK_OVERLAP_CHARS: int = 100          # 相鄰 chunk 重疊字元數
MIN_CHUNK_LENGTH: int = 50             # 最小 chunk 長度（避免過碎片段）
MAX_CHUNK_LENGTH: int = 2000           # 最大 chunk 長度（超過自動分割）

# ── Cleaner 設定 ──────────────────────────────────────
# 要過濾的頁首/頁尾/頁碼正則表達式
HEADER_FOOTER_PATTERNS: list[str] = [
    r"^[-—–]\s*\d+\s*[-—–]$",           # — 1 —  /  - 12 -
    r"^\d+\s*$",                          # 純頁碼
    r"^第\s*\d+\s*頁",                    # 第 1 頁
    r"^Page\s+\d+",                       # Page 1
    r"(?i)^(confidential|internal use)",  # 浮水印文字
]

# ── 集團/同業篩選設定 ─────────────────────────────────
DEFAULT_GROUP: str = "台泥企業團"

COMPARE_KEYWORDS: list[str] = [
    "比較", "差異", "差別", "不同", "對比", "相比",
    "優於", "落後", "領先", "變化", "趨勢", "成長",
    "vs", "VS", "勝過", "超越",
]

# ── Vertex AI / Gemini 設定 ────────────────────────────
GCP_PROJECT: str = _get_secret("GCP_PROJECT", "tcc-personal-project")
GCP_LOCATION: str = _get_secret("GCP_LOCATION", "us-central1")  # Gemini 2.5 系列目前不支援 asia-east1


def _setup_streamlit_adc() -> bool:
    """Streamlit Cloud：將 secrets 中的 service account JSON 寫入暫存檔供 ADC 使用。"""
    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        return True  # 已設定
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "GCP_SERVICE_ACCOUNT" in st.secrets:
            import json, tempfile
            sa = dict(st.secrets["GCP_SERVICE_ACCOUNT"])
            fd, path = tempfile.mkstemp(suffix=".json", prefix="gcp_sa_")
            with os.fdopen(fd, "w") as f:
                json.dump(sa, f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
            return True
    except Exception:
        pass
    return False


def get_genai_client(api_key: str | None = None):
    """建立 genai.Client，使用 Vertex AI（ADC 認證）。

    Cloud Run：自動使用 compute service account。
    Streamlit Cloud：從 secrets 讀取 service account JSON。
    本機開發：需先執行 gcloud auth application-default login。
    """
    from google import genai as _genai

    _setup_streamlit_adc()
    try:
        client = _genai.Client(
            vertexai=True,
            project=GCP_PROJECT,
            location=GCP_LOCATION,
        )
        return client
    except Exception as e:
        raise ValueError(
            f"無法建立 Vertex AI 連線：{e}\n"
            "請確認：(1) 已啟用 Vertex AI API "
            "(2) ADC 已設定（gcloud auth application-default login）"
        ) from e


# ── RAG 動態設定 ──────────────────────────────────────
import time as _time
import threading as _threading

class RagConfig:
    """從 Supabase rag_config 表動態讀取 RAG 搜尋參數。

    - 首次呼叫時從 DB 載入，之後 cache 60 秒
    - DB 不可用時自動 fallback 到程式碼預設值
    - 🛡️ class-level cache 防高併發 DDoS，threading.Lock 防 Cache Stampede
    """

    _DEFAULTS: dict[str, str] = {
        "hybrid_threshold": "0.2",
        "top_k_multiplier": "2",
        "sim_weight":       "0.60",
        "year_weight":      "0.25",
        "source_weight":    "0.15",
        "system_prompt":    "{{DEFAULT}}",
    }
    _CACHE_TTL = 60

    # 🛡️ Class-level 共用 cache
    _shared_cache: dict[str, str] = {}
    _shared_cache_ts: float = 0.0
    _lock = _threading.Lock()  # 🛡️ Double-Check Locking 防 Cache Stampede

    def __init__(self, supabase_client=None):
        self._client = supabase_client

    def _load(self) -> None:
        """從 Supabase 載入設定並更新 class-level cache。"""
        if self._client is None:
            return
        try:
            rows = self._client.table("rag_config").select("key,value").execute().data or []
            RagConfig._shared_cache = {r["key"]: r["value"] for r in rows}
            RagConfig._shared_cache_ts = _time.monotonic()
        except Exception:
            pass

    def _ensure_fresh(self) -> None:
        """若 cache 過期則重新載入（Double-Check Locking 防止 Stampede）。"""
        if _time.monotonic() - RagConfig._shared_cache_ts > self._CACHE_TTL:
            with RagConfig._lock:
                # 第二次檢查：避免等待鎖期間已被另一個 Thread 更新
                if _time.monotonic() - RagConfig._shared_cache_ts > self._CACHE_TTL:
                    self._load()

    def get(self, key: str, cast=str):
        """取得設定值，cast 可指定轉型（float/int/str）。"""
        self._ensure_fresh()
        raw = RagConfig._shared_cache.get(key) or self._DEFAULTS.get(key, "")
        try:
            return cast(raw)
        except (ValueError, TypeError):
            return cast(self._DEFAULTS.get(key, "0"))

    def get_all(self) -> dict[str, str]:
        """取得所有設定值（含 defaults fallback）。"""
        self._ensure_fresh()
        result = dict(self._DEFAULTS)
        result.update(RagConfig._shared_cache)
        return result

    def set(self, key: str, value: str) -> bool:
        """更新設定值到 Supabase，並立即刷新 class-level cache。"""
        if self._client is None:
            return False
        try:
            self._client.table("rag_config").upsert(
                {"key": key, "value": value},
                on_conflict="key"
            ).execute()
            RagConfig._shared_cache[key] = value
            return True
        except Exception:
            return False

    def invalidate_cache(self) -> None:
        """強制下次請求重新載入 cache。"""
        RagConfig._shared_cache_ts = 0.0

