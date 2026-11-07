"""The farm's time zone for display (GET /health). Storage and comparisons stay UTC; nothing here converts data."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib import metadata
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from app.schemas import FarmTimeInfo

SCAN_DAYS = 400


def format_offset(offset: timedelta) -> str:
    minutes = round(offset.total_seconds() / 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _offset_at(zone: ZoneInfo, instant: datetime) -> timedelta:
    return instant.astimezone(zone).utcoffset() or timedelta(0)


def next_offset_change(zone: ZoneInfo, now: datetime, days: int = SCAN_DAYS) -> Optional[Tuple[datetime, timedelta]]:
    """First minute within `days` days at which the zone's UTC offset differs from now: (instant, offset after)."""
    current = _offset_at(zone, now)
    previous = now
    for day in range(1, days + 1):
        probe = now + timedelta(days=day)
        if _offset_at(zone, probe) != current:
            low, high = 0, int((probe - previous).total_seconds() // 60)  # offset at `previous` is old, at +high min is new
            while high - low > 1:
                mid = (low + high) // 2
                if _offset_at(zone, previous + timedelta(minutes=mid)) == current:
                    low = mid
                else:
                    high = mid
            instant = (previous + timedelta(minutes=high)).replace(second=0, microsecond=0)
            return instant, _offset_at(zone, instant)
        previous = probe
    return None


def tzdata_version() -> Optional[str]:
    try:
        return metadata.version("tzdata")
    except metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=8)
def _info(tz_name: str, minute: datetime) -> FarmTimeInfo:
    zone = ZoneInfo(tz_name)
    change = next_offset_change(zone, minute)
    return FarmTimeInfo(
        farm_timezone=tz_name,
        utc_offset_now=format_offset(_offset_at(zone, minute)),
        next_offset_change=change[0].isoformat() if change else None,
        offset_after_change=format_offset(change[1]) if change else None,
        tzdata_version=tzdata_version(),
    )


def farm_time_info(tz_name: str, now: Optional[datetime] = None) -> FarmTimeInfo:
    """Cached per minute: a /health poll costs one dict lookup, not a 400-day scan."""
    now = now or datetime.now(timezone.utc)
    return _info(tz_name, now.replace(second=0, microsecond=0))
