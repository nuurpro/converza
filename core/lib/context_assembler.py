from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.repository import SwitchboardRepository
from starlette.concurrency import run_in_threadpool

VALID_AGENTS = {"milo", "sleyz", "vea"}
WORKSPACE_DIR = Path(__file__).resolve().parents[2]
IDENTITIES_DIR = WORKSPACE_DIR / "identities"


def load_identity_file(agent_slug: str) -> str:
    if agent_slug not in VALID_AGENTS:
        raise ValueError(f"Unknown agent_slug: {agent_slug}")

    path = WORKSPACE_DIR / {"milo": "Milo", "sleyz": "Sleyz", "vea": "Vea"}[agent_slug] / "identity.md"
    if not path.is_file():
        path = IDENTITIES_DIR / f"{agent_slug}.md"
    return path.read_text(encoding="utf-8")


async def assemble_context(
    org_id: str,
    agent_slug: str,
    *,
    repo: SwitchboardRepository,
    query: str | None = None,
) -> dict[str, Any]:
    brand_passport = await repo.get_brand_passport(org_id)
    identity = load_identity_file(agent_slug)
    scoped_memory = await repo.get_agent_memory(org_id, agent_slug, limit=20)
    from services.memory import MemoryStore, render_identity
    knowledge = []
    products = []
    brand_identity = render_identity(brand_passport)
    if getattr(repo, "client", None) is not None:
        search_text = query or next((row["content"] for row in reversed(scoped_memory) if row.get("role") == "user"), "")
        retrieved = await run_in_threadpool(MemoryStore(repo.client).context, org_id, search_text)
        brand_identity = retrieved["identity"]["exports"]
        knowledge = retrieved["knowledge"]
        products = retrieved["products"]
    return {
        "brand_passport": brand_passport,
        "identity": identity,
        "memory": scoped_memory,
        "brand_identity": brand_identity,
        "knowledge": knowledge,
        "current_products": products,
    }
