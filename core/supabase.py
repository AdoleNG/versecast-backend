from supabase import create_client, Client
from core.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY


def get_admin_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)