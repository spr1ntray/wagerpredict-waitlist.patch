from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_account import Account
from eth_utils import is_address, to_checksum_address

from .errors import BlockedError, SoftError
from .http import ProjectHttp
from .utils import normalize_private_key


@dataclass(frozen=True)
class AllowlistStatus:
    enabled: bool
    allowed: bool
    requested: bool
    status: str
    requested_at: str
    already_requested: bool = False

    @property
    def queue_label(self) -> str:
        if self.allowed:
            return "допущен"
        raw = self.status.strip().lower()
        if raw in {"rejected", "denied", "declined"}:
            return "отклонён"
        if raw == "pending" or self.requested or self.already_requested:
            return "в очереди"
        if not self.enabled:
            return "набор закрыт"
        return "нет заявки"


def checksum_from_key(private_key: str) -> str:
    try:
        key = normalize_private_key(private_key)
    except ValueError as exc:
        raise SoftError("invalid_key", "Неверный ключ кошелька") from exc
    try:
        return Account.from_key(key).address
    except Exception as exc:
        raise SoftError("invalid_key", "Неверный ключ кошелька") from exc


def checksum_from_address(raw: str) -> str:
    value = (raw or "").strip()
    if not value or not is_address(value):
        raise SoftError("invalid_address", "Неверный адрес кошелька")
    return to_checksum_address(value)


def normalize_handle(email: str) -> str:
    value = (email or "").strip()
    if len(value) > 254 or "@" not in value:
        raise BlockedError("invalid_email", "Неверная почта")
    local, _, domain = value.partition("@")
    if not local or "." not in domain or " " in value:
        raise BlockedError("invalid_email", "Неверная почта")
    return value


def parse_status(data: Any, *, already_requested: bool = False) -> AllowlistStatus:
    payload = data if isinstance(data, dict) else {}
    status = payload.get("status")
    requested_at = payload.get("requestedAt")
    return AllowlistStatus(
        enabled=bool(payload.get("enabled", True)),
        allowed=bool(payload.get("allowed")),
        requested=bool(payload.get("requested")),
        status="" if status is None else str(status),
        requested_at="" if requested_at is None else str(requested_at),
        already_requested=already_requested or bool(payload.get("alreadyRequested")),
    )


def fetch_status(http: ProjectHttp, address: str) -> AllowlistStatus:
    return parse_status(http.get(f"/api/allowlist/status/{address}"))


def submit_request(http: ProjectHttp, address: str, handle: str) -> dict[str, Any]:
    payload = {"address": address, "handle": handle}
    data = http.post("/api/allowlist/request", payload)
    return data if isinstance(data, dict) else {}


def classify_before_submit(status: AllowlistStatus) -> str:
    if status.allowed:
        return "already_allowed"
    if not status.enabled:
        return "closed"
    if status.requested or status.status.strip().lower() == "pending":
        return "already_queued"
    return "submit"
