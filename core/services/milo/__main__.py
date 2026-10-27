import asyncio
import logging

from services.runtime import load_environment
from db import get_supabase
from lib.repository import SupabaseRepository
from .worker import MiloWorker

if __name__=='__main__':
    load_environment()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(MiloWorker(SupabaseRepository(get_supabase())).run())
