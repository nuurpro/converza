"""Canonical environment loading, independent of the launching directory."""
from pathlib import Path

from dotenv import load_dotenv

CORE_DIR = Path(__file__).resolve().parents[1]


def load_environment(path: Path | None = None) -> None:
    load_dotenv(path if path is not None else CORE_DIR / '.env', override=False)
