from plugin.wager_bot.errors import faucet_reason_message


def test_faucet_already_claimed_is_safe() -> None:
    text = faucet_reason_message("gas", "already_claimed")
    assert "кран" in text.lower() or "Кран" in text
    assert "0x" not in text


def test_faucet_ip_cap_mentions_proxy() -> None:
    text = faucet_reason_message("usdc", "ip_cap")
    assert "прокси" in text.lower()
