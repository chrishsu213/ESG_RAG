"""
config_modules.py — 各模組的 Dataclass 設定

每個 Config 類別就是該模組的「參數說明書」：
  - IDE 自動補全所有設定鍵名
  - 可在測試時傳入不同 config 初始化模組
  - 向下相容：所有欄位都有預設值，傳入 None 即使用預設

使用範例：
    from config_modules import ChunkerConfig
    chunker = SemanticChunker(ChunkerConfig(max_length=3000))
"""
from dataclasses import dataclass, field


@dataclass
class ChunkerConfig:
    """SemanticChunker 切割參數。"""
    max_length: int = 2000          # Parent chunk 最大字元數（超過自動切割）
    child_max_length: int = 400     # Child chunk 最大字元數
    min_length: int = 50            # 最小 chunk 長度（避免過碎）
    overlap: int = 100              # 相鄰 chunk 重疊字元數


@dataclass
class EmbedderConfig:
    """GeminiEmbedder 向量嵌入參數。"""
    model: str = "gemini-embedding-001"   # Google 嵌入模型
    dimension: int = 768                   # 向量維度（HNSW 上限 2000）
    batch_size: int = 200                  # 每次 API 請求最大項目數


@dataclass
class RetrieverConfig:
    """SemanticRetriever 搜尋參數（程式碼預設值；DB 動態設定優先）。"""
    default_top_k: int = 5              # 預設回傳段落數
    hybrid_threshold: float = 0.2       # 混合搜尋相似度門檻
    top_k_multiplier: int = 2           # 候選池倍數（取 top_k * N 再精排）
    sim_weight: float = 0.60            # 語義相似度加權
    year_weight: float = 0.25           # 年份新舊加權
    source_weight: float = 0.15         # 來源類型加權


@dataclass
class CleanerConfig:
    """MarkdownCleaner 清洗參數。"""
    header_footer_patterns: list[str] = field(default_factory=lambda: [
        r"^[-—–]\s*\d+\s*[-—–]$",            # — 1 —  /  - 12 -
        r"^\d+\s*$",                            # 純頁碼
        r"^第\s*\d+\s*頁",                     # 第 1 頁
        r"^Page\s+\d+",                         # Page 1
        r"(?i)^(confidential|internal use)",    # 浮水印文字
    ])
    min_section_length: int = 10        # 過短段落（可能是頁碼殘留）自動過濾
