import asyncio
import logging
from dotenv import load_dotenv
from db import get_supabase
from . import IndexWorker

if __name__ == '__main__':
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(IndexWorker(get_supabase()).run())
