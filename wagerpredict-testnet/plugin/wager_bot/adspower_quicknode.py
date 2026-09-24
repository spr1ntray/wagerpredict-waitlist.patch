from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests

from .errors import SoftError

QUICKNODE_FAUCET_URL = "https://faucet.quicknode.com/binance-smart-chain/bnb-testnet"
ADSPOWER_LOCAL = "http://local.adspower.net:50325"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "local.adspower.net"})
_START_LOCK = threading.Lock()
_PROFILE_LOCKS: dict[str, threading.Lock] = {}
_LAST_START_MONO = 0.0
_MIN_START_INTERVAL_SEC = 1.8
_ADDRESS_SELECTORS = (
    'input[placeholder="0x..."]',
    'input[placeholder*="0x"]',
    'input[name="address"]',
    'input[placeholder*="address" i]',
    'input[placeholder*="wallet" i]',
)
_CLAIM_SELECTORS = (
    'button:has-text("Continue")',
    'button:has-text("Claim")',
    'button:has-text("Request")',
    'button:has-text("Drip")',
    'button:has-text("Get tokens")',
    'button:has-text("Get")',
    '[role="button"]:has-text("Continue")',
    '[role="button"]:has-text("Claim")',
)
_COOKIE_SELECTORS = (
    'button:has-text("Accept")',
    'button:has-text("Decline")',
    'button:has-text("Accept all")',
    'button:has-text("I agree")',
)


def duplicate_adspower_ids(pairs: list[tuple[str, str]]) -> set[str]:
    """Return account ids that share a non-empty AdsPower profile with another account."""
    seen: dict[str, str] = {}
    dupes: set[str] = set()
    for account_id, profile_id in pairs:
        key = (profile_id or "").strip()
        if not key:
            continue
        prev = seen.get(key)
        if prev:
            dupes.add(account_id)
            dupes.add(prev)
        else:
            seen[key] = account_id
    return dupes


def claim_quicknode_tbnb(
    *,
    address: str,
    profile_id: str,
    api_key: str,
    get_native: Callable[[], int],
    min_wei: int,
) -> str:
    profile = (profile_id or "").strip()
    key = (api_key or "").strip()
    if len(profile) < 4:
        raise SoftError("adspower_missing", "Не задан AdsPower-профиль аккаунта")
    if len(key) < 4:
        raise SoftError("adspower_missing", "Не задан AdsPower API key")
    start = int(get_native())
    if start >= int(min_wei):
        return "already"
    with _lock_for(profile):
        return _claim_locked(
            address=address,
            profile_id=profile,
            api_key=key,
            get_native=get_native,
            min_wei=int(min_wei),
            start=start,
        )


def _lock_for(profile_id: str) -> threading.Lock:
    with _START_LOCK:
        lock = _PROFILE_LOCKS.get(profile_id)
        if lock is None:
            lock = threading.Lock()
            _PROFILE_LOCKS[profile_id] = lock
        return lock


def _claim_locked(
    *,
    address: str,
    profile_id: str,
    api_key: str,
    get_native: Callable[[], int],
    min_wei: int,
    start: int,
) -> str:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"Authorization": f"Bearer {api_key}"})
    started = False
    try:
        ws_url = _start_profile(session, profile_id)
        started = True
        _open_and_claim(ws_url, address)
        if _wait_native(get_native, start, min_wei, timeout=120):
            return "claimed"
        raise SoftError("quicknode_faucet", "QuickNode не пополнил tBNB")
    finally:
        if started:
            _stop_profile(session, profile_id)
        session.headers.pop("Authorization", None)
        session.close()


def _start_profile(session: requests.Session, profile_id: str) -> str:
    global _LAST_START_MONO
    url = f"{ADSPOWER_LOCAL}/api/v1/browser/start"
    last = "unknown"
    for attempt in range(1, 7):
        with _START_LOCK:
            now = time.monotonic()
            wait = _MIN_START_INTERVAL_SEC - (now - _LAST_START_MONO)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = session.get(
                    url,
                    params={"user_id": profile_id, "open_tabs": 0, "ip_tab": 0, "headless": 0},
                    timeout=30,
                )
                payload = resp.json() if resp.content else {}
            except Exception as exc:
                _LAST_START_MONO = time.monotonic()
                last = type(exc).__name__
                payload = {}
            else:
                _LAST_START_MONO = time.monotonic()
        if isinstance(payload, dict) and payload.get("code") == 0:
            ws = ((payload.get("data") or {}).get("ws") or {}).get("puppeteer")
            if not ws:
                raise SoftError("adspower_unavailable", "AdsPower не вернул адрес браузера")
            return _assert_local_ws(str(ws))
        msg = str((payload or {}).get("msg") or last)
        last = msg
        if attempt < 6 and any(word in msg.lower() for word in ("too many", "rate", "timeout")):
            time.sleep(min(8.0, 1.5 * attempt + random.uniform(0.4, 1.2)))
            continue
        raise SoftError("adspower_unavailable", "Не удалось открыть AdsPower-профиль")
    raise SoftError("adspower_unavailable", "Не удалось открыть AdsPower-профиль")


def _stop_profile(session: requests.Session, profile_id: str) -> None:
    try:
        session.get(
            f"{ADSPOWER_LOCAL}/api/v1/browser/stop",
            params={"user_id": profile_id},
            timeout=20,
        )
    except Exception:
        return


def _open_and_claim(ws_url: str, address: str) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SoftError("playwright_missing", "Не установлен playwright") from exc
    timeout_ms = 20_000
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(ws_url, timeout=timeout_ms)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(QUICKNODE_FAUCET_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.bring_to_front()
        time.sleep(1.2)
        _dismiss_cookies(page)
        if not _fill_address(page, address, timeout_ms):
            raise SoftError("quicknode_faucet", "Не заполнилось поле адреса QuickNode")
        _select_bnb_testnet(page)
        time.sleep(0.8)
        clicked = False
        for _ in range(6):
            _dismiss_cookies(page)
            if _click_enabled_claim(page, 8_000):
                clicked = True
                time.sleep(8)
                _click_enabled_claim(page, 4_000)
                break
            time.sleep(1.2)
        if not clicked:
            raise SoftError("quicknode_faucet", "Кнопка Continue на QuickNode неактивна")
        time.sleep(6)
        try:
            page.close()
        except Exception:
            pass


def _dismiss_cookies(page: Any) -> None:
    for selector in _COOKIE_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.click(timeout=2_000)
            time.sleep(0.4)
            return
        except Exception:
            continue


def _fill_address(page: Any, address: str, timeout_ms: int) -> bool:
    for selector in _ADDRESS_SELECTORS:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.click(timeout=3_000)
            locator.fill("")
            locator.fill(address, timeout=timeout_ms)
            value = locator.input_value(timeout=2_000)
            if value and value.lower() == address.lower():
                return True
        except Exception:
            continue
    return False


def _select_bnb_testnet(page: Any) -> None:
    try:
        combo = page.get_by_text("BNB Testnet", exact=False).last
        combo.click(timeout=3_000)
        time.sleep(0.3)
        page.get_by_role("option", name="BNB Testnet").click(timeout=3_000)
    except Exception:
        try:
            page.locator("text=BNB Testnet").last.click(timeout=2_000)
        except Exception:
            return


def _click_enabled_claim(page: Any, timeout_ms: int) -> bool:
    for selector in _CLAIM_SELECTORS:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            if locator.is_disabled():
                continue
            locator.scroll_into_view_if_needed()
            locator.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _wait_native(get_native: Callable[[], int], start: int, min_wei: int, *, timeout: int) -> bool:
    deadline = time.monotonic() + max(8, int(timeout))
    last = start
    while time.monotonic() < deadline:
        try:
            last = int(get_native())
        except Exception:
            time.sleep(3)
            continue
        if last >= min_wei or last > start:
            return True
        time.sleep(3)
    try:
        last = int(get_native())
    except Exception:
        return False
    return last >= min_wei or last > start


def _assert_local_ws(ws_url: str) -> str:
    parsed = urlparse(ws_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"ws", "wss", "http", "https"} or host not in _LOCAL_HOSTS:
        raise SoftError("adspower_unavailable", "AdsPower вернул чужой адрес браузера")
    return ws_url
