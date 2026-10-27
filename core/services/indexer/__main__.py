import asyncio
import logging
from services.runtime import load_environment
from db import get_supabase
from . import IndexWorker

if __name__ == '__main__':
    load_environment()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(IndexWorker(get_supabase()).run())
