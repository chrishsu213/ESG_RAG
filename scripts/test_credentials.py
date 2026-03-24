import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env', override=True)

print('SUPABASE_URL:', os.environ.get('SUPABASE_URL', 'MISSING')[:40])
print('GCP_PROJECT:', os.environ.get('GCP_PROJECT', 'MISSING'))
creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').strip('"')
print('GCP_CREDS file exists:', os.path.exists(creds_path), '->', creds_path[:60])

from supabase import create_client
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = c.table('documents').select('id').limit(1).execute()
print('Supabase OK:', len(r.data), 'row(s) returned')
print('ALL GOOD - ready to run batch_ingest.py')
