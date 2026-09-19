from __future__ import annotations

import time
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from .errors import SoftError

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def capsolver_proxy_value(proxy: str) -> str:
    parsed = urlparse(proxy)
    host = parsed.hostname or ""
    port = int(parsed.port or 80)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if user:
        return f"http:{host}:{port}:{user}:{password}"
    return f"http:{host}:{port}"


def is_unsupported_service(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "don't support this service" in text or "not support this service" in text


def _capsolver_soft_error(data: dict[str, Any]) -> SoftError:
    desc = str(data.get("errorDescription") or data.get("errorCode") or "").strip()
    if desc:
        return SoftError("capsolver_error", f"Сервис проверки: {desc[:160]}")
    return SoftError("capsolver_error", "Сервис проверки не принял задачу")


def _post(url: str, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    # Capsolver control plane is not the target site. Account proxy stays inside the task.
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise SoftError("capsolver_network", "Не удалось связаться с сервисом проверки") from exc
    try:
        data = resp.json()
    except Exception:
        data = {"raw": (resp.text or "")[:200], "httpStatus": resp.status_code}
    if isinstance(data, dict) and int(data.get("errorId") or 0) > 0:
        raise _capsolver_soft_error(data)
    if resp.status_code >= 400:
        raise SoftError("capsolver_http", "Сервис проверки вернул ошибку")
    return data if isinstance(data, dict) else {"raw": data}


def solve_hcaptcha(
    api_key: str,
    *,
    site_key: str,
    page_url: str,
    proxy: str | None = None,
    timeout_seconds: int = 180,
) -> str:
    key = (api_key or "").strip()
    if len(key) < 4:
        raise SoftError("capsolver_missing", "Не задан ключ сервиса проверки")

    tasks: list[dict[str, Any]] = [
        {
            "type": "HCaptchaTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
            "userAgent": _UA,
        },
        {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": page_url,
            "websiteKey": site_key,
            "userAgent": _UA,
        },
    ]
    if proxy:
        tasks.append(
            {
                "type": "HCaptchaTask",
                "websiteURL": page_url,
                "websiteKey": site_key,
                "userAgent": _UA,
                "proxy": capsolver_proxy_value(proxy),
            }
        )
    last: Exception | None = None
    for task in tasks:
        try:
            created = _post(
                "https://api.capsolver.com/createTask",
                {"clientKey": key, "task": task},
            )
            task_id = created.get("taskId")
            if not task_id:
                last = SoftError("capsolver_error", "Сервис проверки не создал задачу")
                continue
            return _poll(key, str(task_id), timeout_seconds=timeout_seconds)
        except SoftError as exc:
            last = exc
            if is_unsupported_service(exc):
                raise
            continue
    raise last or SoftError("capsolver_error", "Не удалось пройти проверку человека")


def solve_turnstile(
    api_key: str,
    *,
    site_key: str,
    page_url: str,
    proxy: str | None = None,
    timeout_seconds: int = 180,
) -> str:
    key = (api_key or "").strip()
    if len(key) < 4:
        raise SoftError("capsolver_missing", "Не задан ключ сервиса проверки")

    tasks: list[dict[str, Any]] = [
        {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
    ]
    if proxy:
        tasks.append(
            {
                "type": "AntiTurnstileTask",
                "websiteURL": page_url,
                "websiteKey": site_key,
                "proxy": capsolver_proxy_value(proxy),
            }
        )

    last: Exception | None = None
    for task in tasks:
        try:
            created = _post(
                "https://api.capsolver.com/createTask",
                {"clientKey": key, "task": task},
            )
            task_id = created.get("taskId")
            if not task_id:
                last = SoftError("capsolver_error", "Сервис проверки не создал задачу")
                continue
            return _poll(key, str(task_id), timeout_seconds=timeout_seconds)
        except SoftError as exc:
            last = exc
            continue
    raise last or SoftError("capsolver_error", "Не удалось пройти проверку человека")


def _poll(api_key: str, task_id: str, *, timeout_seconds: int) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(3)
        data = _post(
            "https://api.capsolver.com/getTaskResult",
            {"clientKey": api_key, "taskId": task_id},
        )
        status = data.get("status")
        if status == "ready":
            solution = data.get("solution") or {}
            token = solution.get("token") or solution.get("gRecaptchaResponse")
            if not token:
                raise SoftError("capsolver_empty", "Проверка человека вернула пустой ответ")
            return str(token)
        if status and status not in {"idle", "processing"}:
            raise _capsolver_soft_error(data if isinstance(data, dict) else {})
    raise SoftError("capsolver_timeout", "Проверка человека не успела завершиться")
