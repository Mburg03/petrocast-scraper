import os
import sys
from dataclasses import dataclass


@dataclass
class Config:
    supabase_url: str
    supabase_service_role_key: str
    storage_bucket: str = "scraper-audit"
    retry_wait_seconds: int = 1800
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def load_config() -> Config:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    bucket   = os.environ.get("STORAGE_BUCKET", "scraper-audit").strip()
    retry    = int(os.environ.get("RETRY_WAIT_SECONDS", "1800"))
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    return Config(
        supabase_url=url,
        supabase_service_role_key=key,
        storage_bucket=bucket,
        retry_wait_seconds=retry,
        telegram_bot_token=tg_token,
        telegram_chat_id=tg_chat,
    )
