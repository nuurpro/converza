"""Renderer URL helpers shared by the approved-script submission adapters."""
import os


def _base_url() -> str:
    return os.getenv('MONEYPRINTERTURBO_BASE_URL', 'http://127.0.0.1:8080').rstrip('/')


def _absolute_worker_url(value: str, base_url: str) -> str:
    if value.startswith(('http://', 'https://')):
        return value
    return f"{base_url}/{value.lstrip('/')}"
