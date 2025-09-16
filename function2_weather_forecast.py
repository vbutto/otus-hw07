import json
import os
import logging
import socket
import time
import uuid
from datetime import datetime, timedelta, date
from typing import Any, Dict, Tuple, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Опционально используем requests, если вдруг положишь его в ZIP
try:
    import requests  # type: ignore
except Exception:
    requests = None

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("weather.forecast.nolibs")

YA_KEY = os.getenv("WEATHER_API_KEY", "")
USE_MOCK = (YA_KEY.strip().lower() == "mock" or YA_KEY.strip() == "")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
YANDEX_URL = "https://api.weather.yandex.ru/v2/forecast"

def _ok(payload: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(payload, ensure_ascii=False)}

def _err(msg: str, status: int = 400, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = {"error": msg}
    if extra:
        body.update(extra)
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(body, ensure_ascii=False)}

def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

def _parse_event(event: Dict[str, Any]) -> Tuple[float, float, int, str]:
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

    lat = _first(qs.get("lat"), body.get("lat"), event.get("lat"))
    lon = _first(qs.get("lon"), body.get("lon"), event.get("lon"))
    days = _first(qs.get("days"), body.get("days"), event.get("days"), 5)
    req_id = _first(qs.get("request_id"), body.get("request_id"), str(uuid.uuid4()))

    try:
        lat = float(lat)
        lon = float(lon)
        days = int(days)
    except Exception:
        raise ValueError("lat/lon must be numeric and days must be integer")

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError("lat must be [-90..90], lon must be [-180..180]")
    if not (1 <= days <= 7):
        raise ValueError("days must be 1..7")

    return lat, lon, days, str(req_id)

# HTTP helpers
def _http_get(url: str, params: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: float = 8.0) -> Tuple[Dict[str, Any], int]:
    if requests:
        r = requests.get(url, params=params, headers=headers or {}, timeout=timeout)  # type: ignore
        try:
            return r.json(), r.status_code
        except Exception:
            return {"raw": r.text[:1000]}, r.status_code
    full = f"{url}?{urlencode(params)}" if params else url
    req = Request(full, headers=headers or {}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(body), getattr(resp, "status", 200)
            except Exception:
                return {"raw": body[:1000]}, getattr(resp, "status", 200)
    except HTTPError as e:
        return {"error": f"http {e.code}", "detail": e.reason}, e.code
    except URLError as e:
        return {"error": "network", "detail": str(e)}, 502

def _yandex(lat: float, lon: float, days: int, req_id: str) -> Dict[str, Any]:
    params = {"lat": lat, "lon": lon, "lang": "ru_RU", "limit": min(days, 7), "hours": "false", "extra": "false"}
    t0 = time.time()
    data, code = _http_get(YANDEX_URL, params, headers={"X-Yandex-API-Key": YA_KEY}, timeout=8.0)
    elapsed = (time.time() - t0) * 1000
    logger.info("yandex_req req_id=%s status=%s elapsed_ms=%.1f", req_id, code, elapsed)
    if code != 200:
        raise RuntimeError(f"yandex_status={code} detail={data}")
    return data

def _open_meteo(lat: float, lon: float, days: int, req_id: str) -> Dict[str, Any]:
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
    data, code = _http_get(OPEN_METEO_URL, params, timeout=8.0)
    elapsed = (time.time() - t0) * 1000
    logger.info("openmeteo_req req_id=%s status=%s elapsed_ms=%.1f", req_id, code, elapsed)
    if code != 200:
        raise RuntimeError(f"openmeteo_status={code} detail={data}")
    return data

def _i(v, d): 
    try: return int(v)
    except Exception: return d

def _avg(a, b):
    if a is None and b is None: return None
    if a is None: return b
    if b is None: return a
    return (a + b) / 2

def _icon(c: str) -> str:
    return {
        "clear":"☀️","partly-cloudy":"⛅","cloudy":"☁️","overcast":"☁️",
        "light-rain":"🌦️","rain":"🌧️","heavy-rain":"🌧️","showers":"🌧️",
        "wet-snow":"🌨️","light-snow":"❄️","snow":"❄️","snow-showers":"🌨️",
        "hail":"🌨️","thunderstorm":"⛈️","thunderstorm-with-rain":"⛈️","thunderstorm-with-hail":"⛈️"
    }.get(c, "🌤️")

def _clouds(c: str) -> Optional[int]:
    return {
        "clear":10,"partly-cloudy":30,"cloudy":70,"overcast":100,
        "light-rain":80,"rain":90,"heavy-rain":100,"showers":90,
        "wet-snow":90,"light-snow":80,"snow":90,"snow-showers":100,
        "hail":100,"thunderstorm":90,"thunderstorm-with-rain":95,"thunderstorm-with-hail":100
    }.get(c, 50)

def _desc(c: str) -> str:
    return {
        "clear":"ясно","partly-cloudy":"малооблачно","cloudy":"облачно","overcast":"пасмурно",
        "light-rain":"небольшой дождь","rain":"дождь","heavy-rain":"сильный дождь","showers":"ливень",
        "wet-snow":"дождь со снегом","light-snow":"небольшой снег","snow":"снег","snow-showers":"снегопад",
        "hail":"град","thunderstorm":"гроза","thunderstorm-with-rain":"дождь с грозой","thunderstorm-with-hail":"гроза с градом"
    }.get(c, c)

def _normalize_yandex(data: Dict[str, Any], days: int, lat: float, lon: float) -> Dict[str, Any]:
    info = data.get("info", {})
    tz = (info.get("tzinfo") or {}).get("name", "")
    loc = tz.split("/")[-1].replace("_", " ") if "/" in tz else f"{lat:.3f}, {lon:.3f}"
    fact = data.get("fact", {})
    forecasts = (data.get("forecasts") or [])[:days]
    out = []
    for i, f in enumerate(forecasts):
        parts = f.get("parts", {})
        day = parts.get("day", {}) or parts.get("day_short", {}) or {}
        cond = day.get("condition", "clear")
        t_avg = day.get("temp_avg", fact.get("temp") if i == 0 else None)
        t_min = day.get("temp_min")
        t_max = parts.get("day_short", {}).get("temp_max")
        feels = day.get("feels_like", t_avg)
        out.append({
            "date": f.get("date"),
            "temperature": {"day": _i(t_avg, 0), "min": _i(t_min, _i(t_avg,0)-3), "max": _i(t_max, _i(t_avg,0)+3), "feels_like": _i(feels, _i(t_avg,0))},
            "weather": {"main": cond.title(), "description": _desc(cond), "icon": _icon(cond)},
            "humidity": day.get("humidity", 50),
            "pressure": day.get("pressure_mm", 760),
            "wind_speed": day.get("wind_speed", 0),
            "clouds": _clouds(cond),
            "wind_direction": day.get("wind_dir", "n"),
        })
    return {"location": loc, "coordinates": f"{lat},{lon}", "forecast_days": len(out), "forecast": out,
            "generated_at": datetime.utcnow().isoformat()+"Z", "data_source": "Yandex Weather API"}

def _normalize_open_meteo(data: Dict[str, Any], days: int, lat: float, lon: float) -> Dict[str, Any]:
    daily = data.get("daily", {})
    times = (daily.get("time") or [])[:days]
    out = []
    tmins = daily.get("temperature_2m_min", [])
    tmaxs = daily.get("temperature_2m_max", [])
    winds = daily.get("windspeed_10m_max", [])
    for i, d in enumerate(times):
        tmin = tmins[i] if i < len(tmins) else None
        tmax = tmaxs[i] if i < len(tmaxs) else None
        out.append({
            "date": d,
            "temperature": {"day": _i(_avg(tmin, tmax), 0), "min": _i(tmin, 0), "max": _i(tmax, 0), "feels_like": _i(_avg(tmin, tmax), 0)},
            "weather": {"main": "N/A", "description": "open-meteo daily", "icon": "🌤️"},
            "humidity": None, "pressure": None,
            "wind_speed": winds[i] if i < len(winds) else None,
            "clouds": None, "wind_direction": None
        })
    return {"location": f"{lat:.3f}, {lon:.3f}", "coordinates": f"{lat},{lon}", "forecast_days": len(out),
            "forecast": out, "generated_at": datetime.utcnow().isoformat()+"Z", "data_source": "open-meteo.com"}

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    host = socket.gethostname()
    try:
        lat, lon, days, req_id = _parse_event(event)
    except ValueError as ve:
        logger.warning("f2_validation_fail host=%s err=%s keys=%s", host, ve, list(event.keys()))
        return _err(str(ve), 400)

    logger.info("f2_in host=%s req_id=%s lat=%.4f lon=%.4f days=%d source=%s", host, req_id, lat, lon, days, "YA" if not USE_MOCK else "OM")
    try:
        t0 = time.time()
        if not USE_MOCK:
            raw = _yandex(lat, lon, days, req_id)
            norm = _normalize_yandex(raw, days, lat, lon)
        else:
            raw = _open_meteo(lat, lon, days, req_id)
            norm = _normalize_open_meteo(raw, days, lat, lon)
        norm["req_id"] = req_id
        logger.info("f2_ok req_id=%s source=%s elapsed_ms=%.1f", req_id, norm.get("data_source"), (time.time()-t0)*1000)
        return _ok(norm)
    except Exception as e:
        logger.exception("f2_fail req_id=%s detail=%s", req_id, e)
        return _err("Provider error", 502, {"req_id": req_id})
