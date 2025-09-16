import json
import os
import logging
import socket
import time
import uuid
from typing import Any, Dict, Tuple, Optional

import psycopg2
import requests

# ---------- ЛОГИРОВАНИЕ ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("weather.context")

# ---------- ENV / КОНСТАНТЫ ----------
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "6432"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

F2_URL = os.getenv("F2_URL")  # предпочтительно, если есть HTTP-триггер F2
FORECAST_FUNCTION_ID = os.getenv("FORECAST_FUNCTION_ID")  # иначе будем вызывать Invoke API
CLOUD_FUNCTIONS_API_ENDPOINT = os.getenv(
    "CLOUD_FUNCTIONS_API_ENDPOINT", "https://functions.yandexcloud.net"
)

# ---------- ВСПОМОГАТЕЛЬНЫЕ ----------
def _cors_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }

def _ok(payload: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
    return {"statusCode": status, "headers": _cors_headers(), "body": json.dumps(payload, ensure_ascii=False)}

def _err(msg: str, status: int = 400, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = {"error": msg}
    if extra:
        body.update(extra)
    return {"statusCode": status, "headers": _cors_headers(), "body": json.dumps(body, ensure_ascii=False)}

def _extract_query(event: Dict[str, Any]) -> Dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    if not isinstance(qs, dict):
        qs = {}
    return qs

def _parse_input(event: Dict[str, Any]) -> Tuple[float, float, int, str]:
    qs = _extract_query(event)
    lat = qs.get("lat")
    lon = qs.get("lon")
    user_id = qs.get("user_id", "anonymous")
    days_raw = qs.get("days", 5)

    # валидация
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        raise ValueError("lat/lon must be numeric")

    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        raise ValueError("days must be integer")

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ValueError("lat must be [-90..90], lon must be [-180..180]")

    if not (1 <= days <= 7):
        raise ValueError("days must be in range 1..7")

    return lat, lon, days, user_id

def _get_client_ip(event: Dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    ip = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for") or headers.get("X-Real-IP") or ""
    if "," in ip:
        ip = ip.split(",")[0].strip()
    return ip or "unknown"

def _db_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode=DB_SSLMODE,
    )

def _ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_requests (
            id            BIGSERIAL PRIMARY KEY,
            ts_utc        TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            user_id       TEXT NOT NULL,
            lat           DOUBLE PRECISION NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            forecast_days INTEGER NOT NULL CHECK (forecast_days BETWEEN 1 AND 7),
            ip_address    TEXT,
            req_id        TEXT
        );
        """
    )

def _save_stats(user_id: str, lat: float, lon: float, days: int, ip: str, req_id: str) -> None:
    start = time.time()
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    """
                    INSERT INTO weather_requests (user_id, lat, lon, forecast_days, ip_address, req_id)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (user_id, lat, lon, days, ip, req_id),
                )
        logger.info("db_write_ok req_id=%s elapsed_ms=%.1f", req_id, (time.time() - start) * 1000)
    except Exception as e:
        logger.exception("db_write_fail req_id=%s error=%s", req_id, e)

def _get_iam_token_from_env_or_metadata(req_id: str) -> Optional[str]:
    # 1) ENV (если заранее проброшен)
    env_token = os.getenv("IAM_TOKEN")
    if env_token:
        logger.info("iam_token_source=env req_id=%s", req_id)
        return env_token

    # 2) (Опционально) попытаться получить из metadata — чаще доступно на VM, не в Functions
    try:
        r = requests.get(
            "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
            timeout=1.5,
        )
        if r.ok:
            token = r.json().get("access_token")
            if token:
                logger.info("iam_token_source=metadata req_id=%s", req_id)
                return token
    except Exception as e:
        logger.debug("iam_metadata_unavailable req_id=%s detail=%s", req_id, e)

    logger.info("iam_token_source=absent req_id=%s", req_id)
    return None

def _call_f2(lat: float, lon: float, days: int, req_id: str) -> Tuple[Dict[str, Any], int]:
    payload = {"lat": lat, "lon": lon, "days": days, "request_id": req_id}

    # Вариант 1: есть прямой HTTP URL (HTTP-триггер F2)
    if F2_URL:
        try:
            logger.info("f2_call method=GET via=F2_URL url=%s req_id=%s", F2_URL, req_id)
            resp = requests.get(F2_URL, params=payload, timeout=12)
            data = _safe_json(resp)
            logger.info("f2_resp status=%s req_id=%s", resp.status_code, req_id)
            return data, resp.status_code
        except Exception as e:
            logger.exception("f2_call_fail via=F2_URL req_id=%s error=%s", req_id, e)
            return {"error": "F2 call failed (F2_URL)", "details": str(e)}, 502

    # Вариант 2: вызывать через Invoke API (без публичного триггера)
    if not FORECAST_FUNCTION_ID:
        return {"error": "F2 endpoint not configured"}, 500

    url = f"{CLOUD_FUNCTIONS_API_ENDPOINT.rstrip('/')}/{FORECAST_FUNCTION_ID}"
    headers = {"Content-Type": "application/json"}

    token = _get_iam_token_from_env_or_metadata(req_id)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        # Для совместимости с F2, которая умеет и body, и query — используем JSON body
        logger.info("f2_call method=POST via=invoke url=%s req_id=%s", url, req_id)
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        data = _safe_json(resp)
        logger.info("f2_resp status=%s req_id=%s", resp.status_code, req_id)
        return data, resp.status_code
    except Exception as e:
        logger.exception("f2_call_fail via=invoke req_id=%s error=%s", req_id, e)
        return {"error": "F2 call failed (invoke)", "details": str(e)}, 502

def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:1000]}

# ---------- HANDLER ----------
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    req_id = (event.get("requestContext") or {}).get("requestId") or str(uuid.uuid4())
    host = socket.gethostname()
    logger.info(
        "f1_in host=%s req_id=%s headers=%s qs=%s",
        host,
        req_id,
        (event.get("headers") or {}),
        _extract_query(event),
    )

    # Предварительная проверка ENV, чтобы ошибки были явными в логах
    env_ok = all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD])
    if not env_ok:
        logger.error("env_incomplete req_id=%s db_host=%s db_name=%s db_user=%s", req_id, DB_HOST, DB_NAME, DB_USER)
        return _err("Server misconfiguration (DB env)", 500)

    try:
        lat, lon, days, user_id = _parse_input(event)
    except ValueError as ve:
        logger.warning("validation_fail req_id=%s error=%s", req_id, ve)
        return _err(str(ve), 400)

    ip = _get_client_ip(event)
    logger.info("validated req_id=%s user_id=%s lat=%.4f lon=%.4f days=%d ip=%s", req_id, user_id, lat, lon, days, ip)

    # Пишем статистику (не блокируем ответ при ошибках)
    _save_stats(user_id, lat, lon, days, ip, req_id)

    # Вызываем F2
    f2_payload, f2_status = _call_f2(lat, lon, days, req_id)

    result = {
        "req_id": req_id,
        "requested": {"lat": lat, "lon": lon, "days": days, "user_id": user_id},
        "result": f2_payload,
    }

    # Если F2 отдала 4xx/5xx, прокинем статус наружу
    status_out = 200 if f2_status == 200 else max(f2_status, 502 if f2_status >= 500 else f2_status)
    logger.info("f1_out req_id=%s status=%d", req_id, status_out)
    return _ok(result, status=status_out)
