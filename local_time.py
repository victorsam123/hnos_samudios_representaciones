"""Convert persisted UTC timestamps to Paraguay's local date and time."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


PARAGUAY_TIMEZONE = ZoneInfo("America/Asuncion")


def paraguay_datetime(value: datetime) -> datetime:
    # SQLite returns naive timestamps even when the model specifies timezone=True.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PARAGUAY_TIMEZONE)


def format_paraguay_datetime(value: datetime, date_only: bool = False) -> str:
    pattern = "%d/%m/%Y" if date_only else "%d/%m/%Y %H:%M"
    return paraguay_datetime(value).strftime(pattern)
