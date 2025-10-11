# reservas/utils_time.py
from __future__ import annotations
import time
from typing import Optional
from django.conf import settings
from django.core.cache import cache
from .http_client import session

GOOGLE_TZ_ENDPOINT = "https://maps.googleapis.com/maps/api/timezone/json"

def _fallback_timezone(lat: float, lng: float) -> Optional[str]:
    try:
        from timezonefinder import TimezoneFinder
    except Exception:
        return None
    try:
        tf = TimezoneFinder()
        return tf.timezone_at(lng=float(lng), lat=float(lat))
    except Exception:
        return None

def resolve_tz_from_latlng(lat: float, lng: float, timestamp: Optional[int] = None) -> Optional[str]:
    # 1) cache (30 días)
    ck = f"tz:{float(lat):.5f}:{float(lng):.5f}"
    cached = cache.get(ck)
    if cached:
        return cached

    key = getattr(settings, "GOOGLE_TIMEZONE_API_KEY", None)
    ts = int(timestamp or time.time())

    # 2) intento Google (si hay key)
    if key:
        try:
            resp = session.get(
                GOOGLE_TZ_ENDPOINT,
                params={"location": f"{lat},{lng}", "timestamp": ts, "key": key},
                timeout=getattr(settings, "TIMEZONE_HTTP_TIMEOUT", 4),
            )
            data = resp.json()
            if data.get("status") == "OK":
                tz = data.get("timeZoneId")
                cache.set(ck, tz, 60 * 60 * 24 * 30)  # 30d
                return tz
            # log suave en DEBUG
            if getattr(settings, "DEBUG", False):
                print("TimeZone API error:", data)
        except Exception as e:
            if getattr(settings, "DEBUG", False):
                print("TimeZone API exception:", e)

    # 3) fallback local
    tz = _fallback_timezone(lat, lng)
    if tz:
        cache.set(ck, tz, 60 * 60 * 24 * 30)
    return tz
