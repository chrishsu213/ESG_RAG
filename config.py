"""
config.py — 讀取環境變數與全域常數

支援兩種來源（優先順序）：
  1. Streamlit Cloud secrets (st.secrets) — 透過 _get_secret() 即時讀取
  2. 環境變數 / .env 檔案

注意：SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY、GEMINI_API_KEY 使用
     延遲載入（lazy-loading），確保在 Streamlit Cloud 上
     st.secrets 於首次存取時已經就緒。
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


# ── 延遲載入密鑰 ──────────────────────────────────────
# 各模組 import 時不會立即解析密鑰值，而是在首次存取時才呼叫 _get_secret()。
# 這確保 Streamlit Cloud 的 st.secrets 在讀取時已準備好。
_SECRET_KEYS = {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEY"}
_resolved_secrets: dict[str, str] = {}


def __getattr__(name: str) -> str:
    """Module-level __getattr__：延遲載入密鑰。
    當其他模組執行 `from config import GEMINI_API_KEY` 時，
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
