from __future__ import annotations


class SoftError(RuntimeError):
    """Expected per-account failure with a stable public code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BlockedError(SoftError):
    pass


class PartialError(SoftError):
    def __init__(self, code: str, message: str, data: dict | None = None) -> None:
        super().__init__(code, message)
        self.data = data or {}


SOFT_FAUCET_CODES = {
    "already_claimed",
    "has_balance",
    "already funded",
    "cooldown",
    "disabled",
    "ip_cap",
    "daily_cap",
}


def is_soft_faucet(reason: str) -> bool:
    return str(reason or "").strip().lower() in SOFT_FAUCET_CODES


def faucet_retryable(reason: str) -> bool:
    return str(reason or "").strip().lower() in {"cooldown"}


def faucet_reason_message(kind: str, reason: str) -> str:
    if reason in {"already_claimed", "has_balance"}:
        return "Кран уже выдавал этому кошельку — продолжаем с текущим балансом"
    if reason in {"ip_cap", "daily_cap"}:
        return "Кран ограничил выдачу с этого адреса. Проверьте прокси и повторите позже"
    if reason in {"network_block"}:
        return "Кран не выдаёт через эту сеть. Нужен другой прокси"
    if reason in {"captcha"}:
        return "Проверка человека не прошла"
    if reason in {"faucet_empty", "empty"}:
        return "В кране временно нет средств"
    if reason in {"disabled"}:
        return "Встроенный кран выключен"
    if reason in {"cooldown"}:
        return "Кран ещё на паузе после прошлой выдачи"
    if kind == "gas":
        return "Не удалось получить тестовый газ"
    return "Не удалось получить тестовые USDC"


def classify_tx_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if text.startswith("tx_broadcast:"):
        return "ambiguous"
    if text.startswith("tx_reverted") or "receipt" in text and "status" in text:
        return "confirmed_fail"
    return "pre_broadcast"


def safe_code(exc: BaseException) -> str:
    if isinstance(exc, SoftError):
        return exc.code
    text = str(exc).lower()
    if text.startswith("estimate_failed"):
        return "estimate_failed"
    if text.startswith("tx_rejected"):
        return "tx_rejected"
    if text.startswith("tx_broadcast"):
        return "tx_unconfirmed"
    if text.startswith("tx_reverted"):
        return "tx_reverted"
    if "insufficient funds" in text:
        return "insufficient_funds"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "wrong_chain" in text:
        return "wrong_chain"
    if "rpc_unavailable" in text:
        return "rpc_unavailable"
    return "unexpected_error"
