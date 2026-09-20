from __future__ import annotations

import time
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from .errors import SoftError

IN_URL = "https://2captcha.com/in.php"
RES_URL = "https://2captcha.com/res.php"


def twocaptcha_proxy_pair(proxy: str) -> tuple[str, str]:
    parsed = urlparse(proxy)
    host = parsed.hostname or ""
    port = int(parsed.port or 80)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if user:
        return f"{user}:{password}@{host}:{port}", "HTTP"
    return f"{host}:{port}", "HTTP"


def solve_hcaptcha_2captcha(
    api_key: str,
    *,
    site_key: str,
    page_url: str,
    proxy: str | None = None,
    timeout_seconds: int = 180,
) -> str:
    key = (api_key or "").strip()
    if len(key) < 4:
        raise SoftError("twocaptcha_missing", "Не задан ключ 2Captcha")
    payload: dict[str, Any] = {
        "key": key,
        "method": "hcaptcha",
        "sitekey": site_key,
        "pageurl": page_url,
        "json": 1,
    }
    if proxy:
        proxy_value, proxy_type = twocaptcha_proxy_pair(proxy)
        payload["proxy"] = proxy_value
        payload["proxytype"] = proxy_type
    try:
        created = requests.post(IN_URL, data=payload, timeout=60).json()
    except Exception as exc:
        raise SoftError("twocaptcha_network", "Не удалось связаться с 2Captcha") from exc
    if not isinstance(created, dict) or int(created.get("status") or 0) != 1:
        raise SoftError(
            "twocaptcha_error",
            f"2Captcha: {str(created.get('request') if isinstance(created, dict) else created)[:160]}",
        )
    task_id = str(created.get("request") or "")
    if not task_id:
        raise SoftError("twocaptcha_error", "2Captcha не создала задачу")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(5)
        try:
            data = requests.get(
                RES_URL,
                params={"key": key, "action": "get", "id": task_id, "json": 1},
                timeout=60,
            ).json()
        except Exception as exc:
            raise SoftError("twocaptcha_network", "Не удалось получить ответ 2Captcha") from exc
        if not isinstance(data, dict):
            continue
        if int(data.get("status") or 0) == 1:
            token = str(data.get("request") or "")
            if not token:
                raise SoftError("twocaptcha_empty", "2Captcha вернула пустой токен")
            return token
        wait = str(data.get("request") or "")
        if wait and wait != "CAPCHA_NOT_READY":
            raise SoftError("twocaptcha_error", f"2Captcha: {wait[:160]}")
    raise SoftError("twocaptcha_timeout", "2Captcha не успела решить капчу")
