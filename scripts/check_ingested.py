import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env', override=True)
from supabase import create_client
from datetime import datetime, timezone
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
today = '2026-03-21T00:00:00+00:00'
r = c.table('documents').select('id,file_name,created_at').gte('created_at', today).order('id').execute()
for d in r.data:
    print(f"  id={d['id']}  {d['file_name']}")
print(f'Total: {len(r.data)} docs ingested since yesterday')
