from plugin.wager_bot.allowlist import (
    checksum_from_address,
    checksum_from_key,
    classify_before_submit,
    normalize_handle,
    parse_status,
    submit_request,
)
from plugin.wager_bot.errors import BlockedError, SoftError


HAR_ADDRESS = "0x37075c36958636A91Afa20247eDa4f5499B2e986"
ONE_KEY = "0x" + "00" * 31 + "01"
ONE_ADDRESS = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"


def test_har_address_checksum() -> None:
    assert checksum_from_address(HAR_ADDRESS.lower()) == HAR_ADDRESS
    assert checksum_from_address(HAR_ADDRESS) == HAR_ADDRESS


def test_checksum_from_known_key() -> None:
    assert checksum_from_key(ONE_KEY) == ONE_ADDRESS
    assert checksum_from_key(ONE_KEY[2:]) == ONE_ADDRESS


def test_bad_key_is_soft() -> None:
    try:
        checksum_from_key("not-a-key")
    except SoftError as exc:
        assert exc.code == "invalid_key"
        assert "0x" not in exc.message
    else:
        raise AssertionError("expected invalid key")


def test_handle_keeps_email() -> None:
    assert normalize_handle("  user@example.com ") == "user@example.com"


def test_handle_rejects_garbage() -> None:
    for value in ("", "no-at", "a@b", "user@example", "user @example.com"):
        try:
            normalize_handle(value)
        except BlockedError as exc:
            assert exc.code == "invalid_email"
            if value:
                assert value not in exc.message
        else:
            raise AssertionError(value)


def test_status_labels() -> None:
    empty = parse_status({"enabled": True, "allowed": False, "requested": False, "status": None})
    assert classify_before_submit(empty) == "submit"
    assert empty.queue_label == "нет заявки"

    queued = parse_status(
        {
            "enabled": True,
            "allowed": False,
            "requested": True,
            "status": "pending",
            "requestedAt": "2026-10-07T19:27:37.167797+00:00",
        }
    )
    assert classify_before_submit(queued) == "already_queued"
    assert queued.queue_label == "в очереди"

    allowed = parse_status({"enabled": True, "allowed": True, "requested": True, "status": "approved"})
    assert classify_before_submit(allowed) == "already_allowed"
    assert allowed.queue_label == "допущен"

    closed = parse_status({"enabled": False, "allowed": False, "requested": False, "status": None})
    assert classify_before_submit(closed) == "closed"
    assert closed.queue_label == "набор закрыт"


def test_submit_payload_matches_har() -> None:
    posted: list[tuple[str, dict]] = []

    class FakeHttp:
        def post(self, path: str, payload: dict) -> dict:
            posted.append((path, payload))
            return {"status": "pending", "alreadyRequested": False}

    result = submit_request(FakeHttp(), HAR_ADDRESS, "user@example.com")
    assert posted == [
        (
            "/api/allowlist/request",
            {"address": HAR_ADDRESS, "handle": "user@example.com"},
        )
    ]
    assert result["status"] == "pending"
    assert result["alreadyRequested"] is False
