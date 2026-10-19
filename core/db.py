"""
Supabase client — single async-compatible instance for the entire app.
"""

import os
from supabase import create_client, Client

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url:
            raise RuntimeError("SUPABASE_URL must be set in .env")
        if not key:
            raise RuntimeError("SUPABASE_SERVICE_KEY must be set in .env")
        _client = create_client(url, key)
    return _client
