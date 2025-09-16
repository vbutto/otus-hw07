import json
import os
import logging
import socket
import time
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Опциональные зависимости (если вдруг положишь их в ZIP — будут использованы)
try:
    import requests  # type: ignore
except Exception:
    requests = None  # fallback на urllib

try:
    import psycopg2  # type: ignore
except Exception:
    psycopg2 = None  # логируем и пропускаем запись в БД

# ---------- ЛОГИРОВАНИЕ ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("weather.context.nolibs")

# ---------- ENV ----------
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "6432"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

F2_URL = os.getenv("F2_URL")  # если есть HTTP-триггер F2
FORECAST_FUNCTION_ID = os.getenv("FORECAST_FUNCTION_ID")
CLOUD_FUNCTIONS_API_ENDPOINT = os.getenv("CLOUD_FUNCTIONS_API_ENDPOINT", "https://functions.yandexcloud.net")

# ---------- RESP HELPERS ----------
def _cors() -> Dict[str, str]:
    return {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}

def _ok(payload: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
    return {"statusCode": status, "headers": _cors(), "body": json.dumps(payload, ensure_ascii=False)}

def _err(msg: str, status: int = 400, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = {"error": msg}
    if extra:
        body.update(extra)
    return {"statusCode": status, "headers": _cors(), "body": json.dumps(body, ensure_ascii=False)}

# ---------- PARSE ----------
def _qs(event: Dict[str, Any]) -> Dict[str, Any]:
    q = event.get("queryStringParameters") or {}
    return q if isinstance(q, dict) else {}

def _parse(event: Dict[str, Any]) -> Tuple[float, float, int, str]:
    qs = _qs(event)
    lat, lon = qs.get("lat"), qs.get("lon")
    user_id = qs.get("user_id", "anonymous")
    days_raw = qs.get("days", 5)

    try:
        lat = float(lat)
        lon = float(lon)
        days = int(days_raw)
    except Exception:
        raise ValueError("lat/lon must be numeric and days must be integer")

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError("lat must be [-90..90], lon must be [-180..180]")
    if not (1 <= days <= 7):
        raise ValueError("days must be 1..7")
    return lat, lon, days, user_id

def _client_ip(event: Dict[str, Any]) -> str:
    h = event.get("headers") or {}
    ip = h.get("X-Forwarded-For") or h.get("x-forwarded-for") or h.get("X-Real-IP") or ""
    return (ip.split(",")[0].strip() if "," in ip else ip) or "unknown"

# ---------- HTTP ----------
def _http_get(url: str, params: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: float = 12.0) -> Tuple[Dict[str, Any], int]:
    if requests:
        r = requests.get(url, params=params, headers=headers or {}, timeout=timeout)  # type: ignore
        try:
            return r.json(), r.status_code
        except Exception:
            return {"raw": r.text[:1000]}, r.status_code
    # urllib fallback
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

def _http_post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: float = 12.0) -> Tuple[Dict[str, Any], int]:
    if requests:
        r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)  # type: ignore
        try:
            return r.json(), r.status_code
        except Exception:
            return {"raw": r.text[:1000]}, r.status_code
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = Request(url, data=data, headers=hdrs, method="POST")
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

# ---------- DB (опционально) ----------
def _save_stats(user_id: str, lat: float, lon: float, days: int, ip: str, req_id: str) -> None:
    if psycopg2 is None:
        logger.info("db_skip reason=no_psycopg2 req_id=%s", req_id)
        return
    if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        logger.info("db_skip reason=env_incomplete req_id=%s", req_id)
        return
    t0 = time.time()
    try:
        conn = psycopg2.connect(  # type: ignore
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, sslmode=DB_SSLMODE
        )
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS weather_requests (
              id BIGSERIAL PRIMARY KEY,
              ts_utc TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
              user_id TEXT NOT NULL,
              lat DOUBLE PRECISION NOT NULL,
              lon DOUBLE PRECISION NOT NULL,
              forecast_days INTEGER NOT NULL CHECK (forecast_days BETWEEN 1 AND 7),
              ip_address TEXT,
              req_id TEXT
            );
        """)
        cur.execute(
            "INSERT INTO weather_requests (user_id, lat, lon, forecast_days, ip_address, req_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (user_id, lat, lon, days, ip, req_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("db_write_ok req_id=%s elapsed_ms=%.1f", req_id, (time.time() - t0) * 1000)
    except Exception as e:
        logger.exception("db_write_fail req_id=%s error=%s", req_id, e)

def _iam_token(req_id: str) -> Optional[str]:
    tok = os.getenv("IAM_TOKEN")
    if tok:
        logger.info("iam_source=env req_id=%s", req_id)
        return tok
    # metadata, если когда-то появится (обычно недоступно в CF)
    try:
        body, code = _http_get(
            "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
            {},
            headers={"Metadata-Flavor": "Google"},
            timeout=1.5,
        )
        if code == 200 and isinstance(body, dict) and "access_token" in body:
            logger.info("iam_source=metadata req_id=%s", req_id)
            return body["access_token"]
    except Exception as e:
        logger.debug("iam_metadata_unavailable req_id=%s detail=%s", req_id, e)
    logger.info("iam_source=absent req_id=%s", req_id)
    return None

# ---------- CALL F2 ----------
def _call_f2(lat: float, lon: float, days: int, req_id: str) -> Tuple[Dict[str, Any], int]:
    payload = {"lat": lat, "lon": lon, "days": days, "request_id": req_id}

    if F2_URL:
        logger.info("f2_call via=F2_URL method=GET url=%s req_id=%s", F2_URL, req_id)
        body, code = _http_get(F2_URL, payload, timeout=12.0)
        logger.info("f2_resp via=F2_URL status=%s req_id=%s", code, req_id)
        return body, code

    if not FORECAST_FUNCTION_ID:
        return {"error": "F2 endpoint not configured"}, 500

    url = f"{CLOUD_FUNCTIONS_API_ENDPOINT.rstrip('/')}/{FORECAST_FUNCTION_ID}"
    headers = {}
    tok = _iam_token(req_id)
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    logger.info("f2_call via=invoke method=POST url=%s req_id=%s", url, req_id)
    body, code = _http_post_json(url, payload, headers=headers, timeout=12.0)
    logger.info("f2_resp via=invoke status=%s req_id=%s", code, req_id)
    return body, code

# ---------- HANDLER ----------
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    req_id = (event.get("requestContext") or {}).get("requestId") or str(uuid.uuid4())
    logger.info("f1_in host=%s req_id=%s qs=%s hdr=%s", socket.gethostname(), req_id, _qs(event), (event.get("headers") or {}))
    try:
        lat, lon, days, user = _parse(event)
    except ValueError as ve:
        logger.warning("validation_fail req_id=%s err=%s", req_id, ve)
        return _err(str(ve), 400)

    ip = _client_ip(event)
    logger.info("validated req_id=%s user=%s lat=%.4f lon=%.4f days=%d ip=%s", req_id, user, lat, lon, days, ip)

    _save_stats(user, lat, lon, days, ip, req_id)  # no-op если нет psycopg2

    f2_body, f2_code = _call_f2(lat, lon, days, req_id)
    out = {"req_id": req_id, "requested": {"lat": lat, "lon": lon, "days": days, "user_id": user}, "result": f2_body}
    status = 200 if f2_code == 200 else max(f2_code, 502 if f2_code >= 500 else f2_code)
    logger.info("f1_out req_id=%s status=%d", req_id, status)
    return _ok(out, status=status)
