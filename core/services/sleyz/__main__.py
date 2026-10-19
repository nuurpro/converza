import asyncio
import logging
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/'Sleyz'/'.env')
load_dotenv(ROOT/'core'/'.env')

from db import get_supabase
from lib.repository import SupabaseRepository
from .worker import SleyzWorker

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(levelname)s %(message)s')
    asyncio.run(SleyzWorker(SupabaseRepository(get_supabase())).run())
