import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

MAX_RECOMMENDED_PLATFORMS = 2
FALLBACK_PLATFORMS = ["instagram_reels", "youtube_shorts"]
VALID_DURATIONS = {14, 30}
VALID_LITERACY_LEVELS = {"new", "some_experience", "experienced"}
PROOF_MARKERS = ("testimonial", "patient story", "customer story", "success story", "case study", "social proof")

Engine = Callable[..., Awaitable[str]]


def check_platform_overreach(selected: list[str], literacy_level: str) -> dict[str, Any] | None:
    if len(selected) <= MAX_RECOMMENDED_PLATFORMS:
        return None
    count_word = {3: "three", 4: "four", 5: "five"}.get(len(selected), str(len(selected)))
    explanation = (
        "Starting with two gives us enough repetition to learn what works without splitting your attention."
        if literacy_level == "new"
        else "Two focused channels give the plan enough repetition to produce a useful signal."
    )
    return {
        "blocked": True,
        "recommended": FALLBACK_PLATFORMS.copy(),
        "message": (
            f"You selected {count_word} platforms. We recommend Instagram Reels and YouTube Shorts first. "
            f"{explanation}"
        ),
    }


def derive_literacy_level(signals: dict[str, Any]) -> str:
    tracks_metrics = bool(signals.get("has_tracked_metrics_before"))
    overrode_limit = bool(signals.get("overrode_platform_limit"))
    process = str(signals.get("current_process") or "").lower()
    process_is_structured = any(
        marker in process
        for marker in ("calendar", "weekly", "monthly", "campaign", "experiment", "cpa", "roas", "conversion")
    )
    process_is_advanced = any(marker in process for marker in ("experiment", "cpa", "roas", "conversion"))

    if tracks_metrics and process_is_advanced and overrode_limit:
        return "experienced"
    if tracks_metrics or process_is_structured:
        return "some_experience"
    return "new"


def calculate_resource_commitment(hours_per_week: float, duration_days: int) -> dict[str, Any]:
    if duration_days not in VALID_DURATIONS:
        raise ValueError("duration_days must be 14 or 30")
    if hours_per_week <= 0 or hours_per_week > 80:
        raise ValueError("hours_per_week must be between 0 and 80")

    weeks = duration_days / 7
    videos_per_week = max(1, min(7, int(hours_per_week)))
    target_video_count = max(1, round(videos_per_week * weeks))
    return {
        "hours_per_week": float(hours_per_week),
        "target_video_count": target_video_count,
        "regenerate_lighter_plan": hours_per_week < 3,
        "note": (
            "This estimate applies only when you film the footage yourself. "
            "Vea-rendered videos do not use your filming time."
        ),
    }


def _extract_json(raw: str) -> Any:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start_candidates = [position for position in (cleaned.find("{"), cleaned.find("[")) if position >= 0]
        if not start_candidates:
            raise ValueError("Engine response did not contain JSON")
        start = min(start_candidates)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end < start:
            raise ValueError("Engine response contained incomplete JSON")
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(f"Engine returned invalid JSON: {error.msg}") from error


def parse_calendar_skeleton(raw: str, duration_days: int) -> list[dict[str, Any]]:
    if duration_days not in VALID_DURATIONS:
        raise ValueError("duration_days must be 14 or 30")
    payload = _extract_json(raw)
    rows = payload.get("days") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) != duration_days:
        raise ValueError(f"Calendar skeleton must contain exactly {duration_days} days")

    parsed: list[dict[str, Any]] = []
    seen_days: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Every calendar day must be an object")
        day_number = int(row.get("day_number", 0))
        theme = str(row.get("theme") or "").strip()
        if day_number < 1 or day_number > duration_days or day_number in seen_days:
            raise ValueError("Calendar day numbers must be unique and within the selected duration")
        if not theme:
            raise ValueError(f"Day {day_number} is missing a theme")
        seen_days.add(day_number)
        parsed.append(
            {
                "day_number": day_number,
                "theme": theme,
                "status": "skeleton",
                "script": None,
                "video_url": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "approved_at": None,
            }
        )
    parsed.sort(key=lambda day: day["day_number"])
    if [day["day_number"] for day in parsed] != list(range(1, duration_days + 1)):
        raise ValueError("Calendar skeleton must include every day in sequence")
    return parsed


def parse_day_detail(raw: str, expected_theme: str) -> dict[str, str]:
    payload = _extract_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("Day detail must be a JSON object")
    theme = str(payload.get("theme") or "").strip()
    script = str(payload.get("script") or "").strip()
    if theme.casefold() != expected_theme.strip().casefold():
        raise ValueError(f"Generated detail theme '{theme}' does not match skeleton theme '{expected_theme}'")
    if len(script) < 20:
        raise ValueError("Generated day script is too short")
    return {"theme": expected_theme, "script": script}


def _passport_has_proof(passport: dict[str, Any]) -> bool:
    return any(passport.get(key) for key in ("testimonials", "customer_proof", "case_studies", "social_proof"))


def validate_calendar_skeleton(days: list[dict[str, Any]], passport: dict[str, Any]) -> None:
    if _passport_has_proof(passport):
        return
    unsupported = [day["theme"] for day in days if any(marker in day["theme"].lower() for marker in PROOF_MARKERS)]
    if unsupported:
        raise ValueError(f"Calendar requested unsupported proof without Brand Passport evidence: {unsupported[0]}")


def validate_day_detail(detail: dict[str, str], passport: dict[str, Any]) -> None:
    script = detail["script"]
    passport_text = json.dumps(passport, ensure_ascii=True).lower()
    contact_patterns = (
        r"\b(?:\+?\d[\d\s().-]{7,}\d)\b",
        r"\b(?:https?://|www\.)\S+",
    )
    for pattern in contact_patterns:
        for match in re.findall(pattern, script, flags=re.IGNORECASE):
            rendered = match if isinstance(match, str) else "".join(match)
            if rendered.lower() not in passport_text:
                raise ValueError("Generated script invented a contact detail not present in the Brand Passport")
    if not _passport_has_proof(passport) and any(marker in script.lower() for marker in PROOF_MARKERS):
        raise ValueError("Generated script used unsupported proof without Brand Passport evidence")
    unsupported_claim_patterns = (
        r"\b(?:i am|i'm|meet)\s+[A-Z][a-z]+\b",
        r"\bno wait(?:ing)?\b",
        r"\bno appointment needed\b",
        r"\binstant(?:ly)?\b",
        r"\bpain (?:is )?gone\b",
        r"\bfeel better(?: in (?:hours|minutes|days))?\b",
        r"\bease your pain\b",
        r"\brelief starts (?:today|now)\b",
        r"\bquick visit\b",
        r"\bafter treatment\b",
        r"\bfix it fast\b",
        r"\btreat(?:ment)?\b.{0,24}\bright away\b",
        r"\bstart treatment (?:in|within)\b",
        r"\ball in one day\b",
        r"\btrusted\b",
        r"\brelief\b",
        r"\btreat(?:ment|s|ed|ing)?\b",
        r"\bevaluates? your pain\b",
        r"\b0\s*minutes?\b",
        r"\bguaranteed\b",
    )
    for pattern in unsupported_claim_patterns:
        for match in re.findall(pattern, script, flags=re.IGNORECASE):
            rendered = match if isinstance(match, str) else "".join(match)
            if rendered.lower() not in passport_text:
                raise ValueError(f"Generated script made an unsupported claim: {rendered}")


def _brand_context(passport: dict[str, Any]) -> str:
    return json.dumps(
        {
            "brand_name": passport.get("brand_name"),
            "industry": passport.get("industry"),
            "core_offer": passport.get("core_offer"),
            "target_audience": passport.get("target_audience"),
            "target_location": passport.get("target_location"),
            "tone": passport.get("tone"),
        },
        ensure_ascii=True,
    )


async def generate_calendar_skeleton(
    *,
    passport: dict[str, Any],
    duration_days: int,
    platforms: list[str],
    target_video_count: int,
    engine: Engine | None = None,
) -> list[dict[str, Any]]:
    if engine is None:
        from lib.engine import call_engine

        engine = call_engine
    system_prompt = (
        "You are Milo, Converza's marketing strategist. Build practical plans from the supplied Brand Passport. "
        "Do not invent trends, results, customer proof, patient stories, testimonials, case studies, social proof, "
        "or performance data. Never create a proof-based theme unless that proof exists in the Brand Passport. "
        "Return valid JSON only."
    )
    user_prompt = (
        f"Create exactly {duration_days} calendar entries for this brand. Every calendar day must appear. "
        f"Plan {target_video_count} production days; use the remaining days for lightweight preparation, review, "
        "repurposing, or rest so the plan fits the owner's capacity. Platforms: {', '.join(platforms)}. "
        "Return only this shape: {\"days\":[{\"day_number\":1,\"theme\":\"short specific theme\"}]}. "
        "Keep every theme under 10 words and vary the content angle.\n\n"
        f"BRAND PASSPORT:\n{_brand_context(passport)}"
    )
    for attempt in range(2):
        raw = await engine(system_prompt, user_prompt, max_tokens=1200)
        try:
            days = parse_calendar_skeleton(raw, duration_days)
            validate_calendar_skeleton(days, passport)
            return days
        except ValueError as error:
            if attempt == 1:
                raise
            user_prompt += (
                f"\n\nYour previous output was rejected: {error}. Correct that issue and return the complete JSON again."
            )
    raise RuntimeError("Calendar skeleton generation exhausted its retry budget")


async def generate_day_detail(
    *,
    passport: dict[str, Any],
    day: dict[str, Any],
    platforms: list[str],
    engine: Engine | None = None,
) -> dict[str, str]:
    if engine is None:
        from lib.engine import call_engine

        engine = call_engine
    theme = str(day["theme"])
    system_prompt = (
        "You are Milo, Converza's marketing strategist. Write an executable short-form content script from the "
        "Brand Passport. Do not claim trend research or invent product facts, people, testimonials, results, URLs, "
        "phone numbers, or contact details. Use a generic CTA such as 'send us a message' unless the Brand Passport "
        "contains the exact contact detail. Do not name a spokesperson or claim zero wait, instant care, no appointment, "
        "guaranteed relief, a quick outcome, post-treatment success, or any quantified outcome unless the exact fact "
        "is in the Brand Passport. If the offer says consultation, do not turn that into treatment or relief. "
        "Describe the consultation and use 'send us a message' instead. Return valid JSON only."
    )
    user_prompt = (
        f"Write the detailed script for calendar day {day['day_number']}. The locked skeleton theme is exactly: "
        f"{theme}. The response theme must repeat that exact string. Write a second-by-second 15-30 second script "
        f"for {', '.join(platforms)} with hook, scenes, spoken lines, on-screen text, and CTA. "
        "Return only a JSON object with keys theme and script. "
        f"Set theme to exactly '{theme}'.\n\n"
        f"BRAND PASSPORT:\n{_brand_context(passport)}"
    )
    for attempt in range(2):
        raw = await engine(system_prompt, user_prompt, max_tokens=1800)
        try:
            detail = parse_day_detail(raw, expected_theme=theme)
            validate_day_detail(detail, passport)
            return detail
        except ValueError as error:
            if attempt == 1:
                raise
            user_prompt += (
                f"\n\nYour previous output was rejected: {error}. Correct that issue and return the complete JSON again."
            )
    raise RuntimeError("Day detail generation exhausted its retry budget")
