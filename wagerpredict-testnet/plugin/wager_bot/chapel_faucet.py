from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from web3 import Web3

from .capsolver import solve_hcaptcha
from .errors import SoftError

CHAPEL_FAUCET_WS = "wss://testnet.bnbchain.org/faucet-smart/api"
CHAPEL_FAUCET_PAGE = "https://www.bnbchain.org/en/testnet-faucet"
CHAPEL_HCAPTCHA_SITEKEY = "d9a9ee67-74da-4601-9f31-efe6a297a5cc"
CHAPEL_FAUCET_MIN_MAINNET_WEI = 2_000_000_000_000_000  # 0.002 BNB on BSC mainnet
CHAPEL_FAUCET_DROP_WEI = 300_000_000_000_000_000  # 0.3 tBNB, HAR value 0x429d069189e0000
MAINNET_RPCS = (
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.binance.org",
    "https://bsc-dataseed1.bnbchain.org",
    "https://bsc-rpc.publicnode.com",
    "https://1rpc.io/bnb",
)


def chapel_claim_payload(address: str, captcha: str) -> dict[str, str | int]:
    return {
        "tier": 0,
        "url": Web3.to_checksum_address(address),
        "symbol": "BNB",
        "captcha": captcha,
    }


def classify_chapel_error(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    low = raw.lower()
    if "0.002" in low or "mainnet" in low:
        return (
            "chapel_mainnet_bnb",
            "Кран Chapel требует ≥0.002 BNB в BSC mainnet на этом кошельке",
        )
    if not raw:
        return "chapel_faucet", "Кран BNB Chain не выдал tBNB"
    return "chapel_faucet", f"Кран BNB Chain: {raw[:160]}"


def should_skip_chapel_for_mainnet(have: int | None) -> bool:
    return have is not None and have < CHAPEL_FAUCET_MIN_MAINNET_WEI


def mainnet_bnb_wei(address: str, proxy: str | None = None, timeout: int = 12) -> int | None:
    if not proxy:
        return None
    checksum = Web3.to_checksum_address(address)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [checksum, "latest"]}
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    session = requests.Session()
    session.headers.update(headers)
    session.proxies = {"http": proxy, "https": proxy}
    for url in MAINNET_RPCS:
        try:
            resp = session.post(url, json=payload, timeout=timeout)
            data = resp.json()
            result = data.get("result") if isinstance(data, dict) else None
            if isinstance(result, str) and result.startswith("0x"):
                return int(result, 16)
        except Exception:
            continue
    return None


def claim_chapel_tbnb(
    *,
    address: str,
    capsolver_key: str,
    proxy: str | None = None,
    protect=None,
    timeout: int = 90,
) -> str:
    if not proxy:
        raise SoftError("invalid_proxy", "Без прокси кран Chapel не вызываем")
    have = mainnet_bnb_wei(address, proxy=proxy)
    if should_skip_chapel_for_mainnet(have):
        raise SoftError(
            "chapel_mainnet_bnb",
            "Кран Chapel требует ≥0.002 BNB в BSC mainnet на этом кошельке",
        )
    token = solve_hcaptcha(
        capsolver_key,
        site_key=CHAPEL_HCAPTCHA_SITEKEY,
        page_url=CHAPEL_FAUCET_PAGE,
        proxy=proxy,
    )
    if protect is not None:
        token = protect(token) or token
    return _ws_claim(address, token, proxy=proxy, timeout=timeout)


def _ws_claim(address: str, captcha: str, *, proxy: str | None, timeout: int) -> str:
    try:
        from websocket import WebSocketTimeoutException, create_connection
    except ImportError as exc:
        raise SoftError("chapel_ws", "Нет библиотеки websocket-client") from exc

    kwargs: dict[str, Any] = {
        "timeout": min(30, timeout),
        "origin": "https://www.bnbchain.org",
        "header": ["User-Agent: Mozilla/5.0"],
    }
    if proxy:
        parsed = urlparse(proxy)
        if parsed.hostname:
            kwargs["http_proxy_host"] = parsed.hostname
            kwargs["http_proxy_port"] = parsed.port or 80
            if parsed.username is not None:
                kwargs["http_proxy_auth"] = (
                    unquote(parsed.username),
                    unquote(parsed.password or ""),
                )
    ws = create_connection(CHAPEL_FAUCET_WS, **kwargs)
    try:
        ws.send(json.dumps(chapel_claim_payload(address, captcha)))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = ws.recv()
            except WebSocketTimeoutException:
                continue
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("success"):
                return "claimed"
            if data.get("error"):
                code, message = classify_chapel_error(str(data.get("error")))
                raise SoftError(code, message)
        raise SoftError("chapel_timeout", "Кран BNB Chain не ответил вовремя")
    finally:
        try:
            ws.close()
        except Exception:
            pass
