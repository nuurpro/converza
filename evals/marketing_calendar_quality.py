"""Periodic paid eval for calendar theme consistency.

Run manually with: python evals/marketing_calendar_quality.py
This intentionally calls the configured Groq model.
"""

import asyncio
import json

from dotenv import load_dotenv

from lib.engine import call_engine
from lib.marketing_calendar import generate_calendar_skeleton, generate_day_detail

load_dotenv()


async def main() -> None:
    passport = {
        "brand_name": "Converza",
        "industry": "B2B marketing software",
        "core_offer": "AI agents draft marketing content and DM replies, and render video. Every output requires human approval.",
        "target_audience": "E-commerce founders and B2B teams managing marketing with small teams",
        "tone": "direct, precise",
    }
    days = await generate_calendar_skeleton(
        passport=passport,
        duration_days=14,
        platforms=["instagram_reels", "youtube_shorts"],
        target_video_count=4,
        engine=call_engine,
    )
    details = [
        await generate_day_detail(
            passport=passport,
            day=day,
            platforms=["instagram_reels", "youtube_shorts"],
            engine=call_engine,
        )
        for day in (days[0], days[4], days[9])
    ]
    assert len(days) == 14
    assert all(detail["theme"] == source["theme"] for detail, source in zip(details, (days[0], days[4], days[9])))
    print(json.dumps({"skeleton_days": len(days), "checked_details": details}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
