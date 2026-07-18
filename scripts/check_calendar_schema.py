"""Read-only readiness check for the managed marketing calendar migration."""

from dotenv import load_dotenv

from db import get_supabase

load_dotenv()


def main() -> None:
    try:
        result = get_supabase().table("marketing_calendars").select("id").limit(1).execute()
    except Exception as error:
        print(f"marketing_calendars unavailable: {error}")
        raise SystemExit(1) from None
    print(f"marketing_calendars available; sample_rows={len(result.data or [])}")


if __name__ == "__main__":
    main()
