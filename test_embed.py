"""Quick test: embedding model & Supabase connection"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from config import GEMINI_API_KEY, EMBEDDING_MODEL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from supabase import create_client

# Test 1: Supabase connection
print("=== Test 1: Supabase Connection ===")
try:
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    res = client.table("documents").select("id", count="exact").execute()
    print(f"OK! Documents count: {res.count}")
except Exception as e:
    print(f"FAIL: {e}")

# Test 2: Embedding
print(f"\n=== Test 2: Embedding (model={EMBEDDING_MODEL}) ===")
try:
    from modules.embedder import GeminiEmbedder
    embedder = GeminiEmbedder()
    result = embedder.embed_text("ESG test query")
    print(f"OK! Dimension: {len(result)}")
    print(f"First 5 values: {result[:5]}")
except Exception as e:
    print(f"FAIL: {e}")

print("\nDone!")
