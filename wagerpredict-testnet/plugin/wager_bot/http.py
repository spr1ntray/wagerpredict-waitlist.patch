from __future__ import annotations

import time
from typing import Any

import requests

from .config import API_BASE, API_ORIGIN
from .errors import SoftError
from .utils import normalize_proxy


def _network_error(exc: BaseException) -> SoftError:
    if isinstance(exc, requests.exceptions.ProxyError):
        return SoftError("proxy_error", "Прокси не пускает запрос")
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return SoftError("http_timeout", "API проекта не ответило вовремя")
    if isinstance(exc, requests.exceptions.SSLError):
        return SoftError("tls_error", "Не удалось установить защищённое соединение")
    return SoftError("http_network", "Нет ответа от API проекта")


class ProjectHttp:
    def __init__(self, proxy: str | None, timeout: int = 45) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": "WagerPredictSoft/1.0",
                "Accept": "application/json",
                "Origin": API_ORIGIN,
                "Referer": f"{API_ORIGIN}/",
            }
        )
        try:
            proxy_url = normalize_proxy(proxy)
        except ValueError as exc:
            raise SoftError("invalid_proxy", "Неверный формат прокси") from exc
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        return self._decode(self._request("GET", url, params=params))

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        return self._decode(
            self._request(
                "POST",
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last: Exception | None = None
        for attempt in range(3):
            try:
                return self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                last = exc
                if attempt + 1 >= 3:
                    break
                time.sleep(0.6 * (attempt + 1))
        raise _network_error(last or RuntimeError("http_network")) from last

    def _decode(self, resp: requests.Response) -> Any:
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            reason = ""
            if isinstance(data, dict):
                reason = str(data.get("reason") or data.get("error") or "")
            if resp.status_code == 429:
                raise SoftError(reason or "rate_limited", "API проекта временно ограничило запросы")
            raise SoftError(reason or f"http_{resp.status_code}", "API проекта вернуло ошибку")
        return data
