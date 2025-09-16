import json
import os
import logging
import socket
import time
import uuid
from typing import Any, Dict, Tuple

import requests
from datetime import datetime, timedelta, date

# ---------- ЛОГИРОВАНИЕ ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("weather.forecast")

# ---------- ENV / ИСТОЧНИКИ ----------
YA_WEATHER_KEY = os.getenv("WEATHER_API_KEY", "")
USE_MOCK = (YA_WEATHER_KEY.strip().lower() == "mock" or YA_WEATHER_KEY.strip() == "")

# Можно переключиться на Open-Meteo без ключа, если нужно:
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


# ---------- ВСПОМОГАТЕЛЬНЫЕ ----------
def _ok(payload: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(payload, ensure_ascii=False)}

def _err(msg: str, status: int = 400, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = {"error": msg}
    if extra:
        body.update(extra)
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(body, ensure_ascii=False)}

def _parse_event(event: Dict[str, Any]) -> Tuple[float, float, int, str]:
    # поддержа queryStringParameters, JSON body и “плоский” event
    body = {}
    if "body" in event:
        if isinstance(event["body"], str):
            try:
                body = json.loads(event["body"])
            except Exception:
                body = {}
        elif isinstance(event["body"], dict):
            body = event["body"]

    qs = event.get("queryStringParameters") or {}
    if not isinstance(qs, dict):
        qs = {}

    src = body if body else event
    lat = _first_non_none(qs.get("lat"), src.get("lat"))
    lon = _first_non_none(qs.get("lon"), src.get("lon"))
    days = _first_non_none(qs.get("days"), src.get("days"), 5)
    req_id = _first_non_none(qs.get("request_id"), src.get("request_id"), str(uuid.uuid4()))

    try:
        lat = float(lat)
        lon = float(lon)
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("lat/lon must be numeric and days must be integer")

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ValueError("lat must be [-90..90], lon must be [-180..180]")
    if not (1 <= days <= 7):
        raise ValueError("days must be in range 1..7")

    return lat, lon, days, str(req_id)

def _first_non_none(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

# ---------- ВНЕШНИЕ ИСТОЧНИКИ ----------
def _get_from_yandex_weather(lat: float, lon: float, days: int, req_id: str) -> Dict[str, Any]:
    url = "https://api.weather.yandex.ru/v2/forecast"
    headers = {"X-Yandex-API-Key": YA_WEATHER_KEY}
    params = {
        "lat": lat,
        "lon": lon,
        "lang": "ru_RU",
        "limit": min(days, 7),
        "hours": False,
        "extra": False,
    }
    start = time.time()
    r = requests.get(url, headers=headers, params=params, timeout=8)
    elapsed = (time.time() - start) * 1000
    logger.info("yandex_req req_id=%s status=%s elapsed_ms=%.1f url=%s", req_id, r.status_code, elapsed, r.url)
    if not r.ok:
        raise RuntimeError(f"yandex_status={r.status_code}")
    return r.json()

def _get_from_open_meteo(lat: float, lon: float, days: int, req_id: str) -> Dict[str, Any]:
    # fallback без ключа
    start = date.today()
    end = start + timedelta(days=days - 1)
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "windspeed_10m_max"],
        "timezone": "auto",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    t0 = time.time()
    r = requests.get(OPEN_METEO_URL, params=params, timeout=8)
    elapsed = (time.time() - t0) * 1000
    logger.info("openmeteo_req req_id=%s status=%s elapsed_ms=%.1f url=%s", req_id, r.status_code, elapsed, r.url)
    if not r.ok:
        raise RuntimeError(f"openmeteo_status={r.status_code}")
    return r.json()

# ---------- НОРМАЛИЗАЦИЯ ----------
def _normalize_yandex(data: Dict[str, Any], requested_days: int, lat: float, lon: float) -> Dict[str, Any]:
    location_info = data.get("info", {})
    tz_name = (location_info.get("tzinfo") or {}).get("name", "")
    location_name = tz_name.split("/")[-1].replace("_", " ") if "/" in tz_name else f"{lat:.3f}, {lon:.3f}"

    fact = data.get("fact", {})
    forecasts = data.get("forecasts", [])[:requested_days]
    out = []
    for i, d in enumerate(forecasts):
        parts = d.get("parts", {})
        day = parts.get("day", {}) or parts.get("day_short", {}) or {}
        cond = day.get("condition", "clear")
        temp_avg = day.get("temp_avg", fact.get("temp") if i == 0 else None)
        temp_min = day.get("temp_min", None)
        temp_max = parts.get("day_short", {}).get("temp_max", None)
        feels = day.get("feels_like", temp_avg)
        out.append({
            "date": d.get("date"),
            "temperature": {
                "day": _i(temp_avg, 0),
                "min": _i(temp_min, _i(temp_avg, 0) - 3),
                "max": _i(temp_max, _i(temp_avg, 0) + 3),
                "feels_like": _i(feels, _i(temp_avg, 0)),
            },
            "weather": {
                "main": cond.title(),
                "description": _condition_desc(cond),
                "icon": _icon(cond),
            },
            "humidity": day.get("humidity", 50),
            "pressure": day.get("pressure_mm", 760),
            "wind_speed": day.get("wind_speed", 0),
            "clouds": _clouds(cond),
            "wind_direction": day.get("wind_dir", "n"),
        })
    return {
        "location": location_name,
        "coordinates": f"{lat},{lon}",
        "forecast_days": len(out),
        "forecast": out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_source": "Yandex Weather API",
    }

def _normalize_open_meteo(data: Dict[str, Any], requested_days: int, lat: float, lon: float) -> Dict[str, Any]:
    daily = data.get("daily", {})
    dates = daily.get("time", [])[:requested_days]
    out = []
    for i, day in enumerate(dates):
        out.append({
            "date": day,
            "temperature": {
                "day": _i(_avg(daily.get("temperature_2m_min", []), daily.get("temperature_2m_max", []), i), 0),
                "min": _i(_safe_idx(daily.get("temperature_2m_min", []), i), 0),
                "max": _i(_safe_idx(daily.get("temperature_2m_max", []), i), 0),
                "feels_like": _i(_avg(daily.get("temperature_2m_min", []), daily.get("temperature_2m_max", []), i), 0),
            },
            "weather": {
                "main": "N/A",
                "description": "open-meteo daily",
                "icon": "🌤️",
            },
            "humidity": None,
            "pressure": None,
            "wind_speed": _safe_idx(daily.get("windspeed_10m_max", []), i),
            "clouds": None,
            "wind_direction": None,
        })
    return {
        "location": f"{lat:.3f}, {lon:.3f}",
        "coordinates": f"{lat},{lon}",
        "forecast_days": len(out),
        "forecast": out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_source": "open-meteo.com",
    }

def _safe_idx(arr, idx):
    try:
        return arr[idx]
    except Exception:
        return None

def _avg(a, b, i):
    va = _safe_idx(a, i)
    vb = _safe_idx(b, i)
    if va is None and vb is None:
        return None
    if va is None:
        return vb
    if vb is None:
        return va
    return (va + vb) / 2

def _i(v, default):
    try:
        return int(v)
    except Exception:
        return default

def _condition_desc(c: str) -> str:
    mapping = {
        "clear": "ясно",
        "partly-cloudy": "малооблачно",
        "cloudy": "облачно",
        "overcast": "пасмурно",
        "light-rain": "небольшой дождь",
        "rain": "дождь",
        "heavy-rain": "сильный дождь",
        "showers": "ливень",
        "wet-snow": "дождь со снегом",
        "light-snow": "небольшой снег",
        "snow": "снег",
        "snow-showers": "снегопад",
        "hail": "град",
        "thunderstorm": "гроза",
        "thunderstorm-with-rain": "дождь с грозой",
        "thunderstorm-with-hail": "гроза с градом",
    }
    return mapping.get(c, c)

def _icon(c: str) -> str:
    mapping = {
        "clear": "☀️", "partly-cloudy": "⛅", "cloudy": "☁️", "overcast": "☁️",
        "light-rain": "🌦️", "rain": "🌧️", "heavy-rain": "🌧️", "showers": "🌧️",
        "wet-snow": "🌨️", "light-snow": "❄️", "snow": "❄️", "snow-showers": "🌨️",
        "hail": "🌨️", "thunderstorm": "⛈️", "thunderstorm-with-rain": "⛈️", "thunderstorm-with-hail": "⛈️",
    }
    return mapping.get(c, "🌤️")

def _clouds(c: str) -> int | None:
    mapping = {
        "clear": 10, "partly-cloudy": 30, "cloudy": 70, "overcast": 100,
        "light-rain": 80, "rain": 90, "heavy-rain": 100, "showers": 90,
        "wet-snow": 90, "light-snow": 80, "snow": 90, "snow-showers": 100,
        "hail": 100, "thunderstorm": 90, "thunderstorm-with-rain": 95, "thunderstorm-with-hail": 100,
    }
    return mapping.get(c, 50)

# ---------- HANDLER ----------
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    host = socket.gethostname()
    try:
        lat, lon, days, req_id = _parse_event(event)
    except ValueError as ve:
        logger.warning("f2_validation_fail host=%s error=%s event_keys=%s", host, ve, list(event.keys()))
        return _err(str(ve), 400)

    logger.info(
        "f2_in host=%s req_id=%s lat=%.4f lon=%.4f days=%d ya_key=%s",
        host, req_id, lat, lon, days, "set" if not USE_MOCK else "mock",
    )

    try:
        t0 = time.time()
        if not USE_MOCK:
            raw = _get_from_yandex_weather(lat, lon, days, req_id)
            norm = _normalize_yandex(raw, days, lat, lon)
        else:
            raw = _get_from_open_meteo(lat, lon, days, req_id)
            norm = _normalize_open_meteo(raw, days, lat, lon)

        elapsed = (time.time() - t0) * 1000
        logger.info("f2_ok req_id=%s source=%s elapsed_ms=%.1f", req_id, norm.get("data_source"), elapsed)
        norm["req_id"] = req_id
        return _ok(norm)

    except requests.RequestException as re:
        logger.exception("f2_http_fail req_id=%s detail=%s", req_id, re)
        return _err("Upstream weather provider failed", 502, {"req_id": req_id})
    except Exception as e:
        logger.exception("f2_unhandled req_id=%s detail=%s", req_id, e)
        return _err("Internal error", 500, {"req_id": req_id})
