from plugin.wager_bot.chapel_faucet import (
    CHAPEL_FAUCET_DROP_WEI,
    CHAPEL_FAUCET_MIN_MAINNET_WEI,
    chapel_claim_payload,
    classify_chapel_error,
)


def test_chapel_claim_payload_checksums_address() -> None:
    payload = chapel_claim_payload("0xe4ca64d8ec9eadddb310e68b6f0a67b269a39cde", "P1_token")
    assert payload["tier"] == 0
    assert payload["symbol"] == "BNB"
    assert payload["captcha"] == "P1_token"
    assert payload["url"] == "0xE4Ca64D8eC9eaddDB310E68B6f0a67B269a39CDE"


def test_chapel_error_requires_mainnet_bnb() -> None:
    code, message = classify_chapel_error("insufficient BNB on BSC mainnet        (require >=0.002BNB)")
    assert code == "chapel_mainnet_bnb"
    assert "0.002" in message
    assert "mainnet" in message.lower() or "BSC" in message


def test_chapel_error_other() -> None:
    code, message = classify_chapel_error("rate limited")
    assert code == "chapel_faucet"
    assert message


def test_chapel_drop_and_mainnet_floor() -> None:
    assert CHAPEL_FAUCET_MIN_MAINNET_WEI == 2_000_000_000_000_000
    assert CHAPEL_FAUCET_DROP_WEI == 300_000_000_000_000_000
