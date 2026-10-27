import asyncio
import logging
from services.runtime import load_environment

load_environment()

from db import get_supabase
from lib.repository import SupabaseRepository
from .worker import SleyzWorker

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(levelname)s %(message)s')
    asyncio.run(SleyzWorker(SupabaseRepository(get_supabase())).run())
