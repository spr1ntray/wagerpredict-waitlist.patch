from plugin.wager_bot.flow import already_linked, farm_status, linked_result, tradable_quote
from plugin.wager_bot.options import farm_config
from plugin.wager_bot.referral import public_slug


def test_already_linked_stats() -> None:
    assert already_linked({"referrer": "0xabc"}) is True
    assert already_linked({"referred_by": "alice"}) is True
    assert already_linked({"attributed": True}) is True
    assert already_linked({"slug": "alice", "total_referred": 0}) is False


def test_existing_slug_is_kept() -> None:
    assert public_slug({"slug": "fallex"}) == "fallex"


def test_linked_result_treats_already_as_success() -> None:
    assert linked_result("already") is True
    assert linked_result("attributed") is True
    assert linked_result("missing") is False


def test_zero_quote_is_not_tradable() -> None:
    assert tradable_quote(0) is False
    assert tradable_quote(12) is True


def test_bets_then_rpc_error_is_partial() -> None:
    status, message = farm_status(bets=4, vault=0, error_code="tx_rejected")
    assert status == "partial"
    assert "часть" in message.lower()


def test_clean_cycle_with_bets_succeeds() -> None:
    status, message = farm_status(bets=3, vault=1, error_code=None)
    assert status == "succeeded"
    assert "завершён" in message.lower()


def test_vault_option_caps_at_15k() -> None:
    cfg = farm_config({"vault_usdc_from": 100, "vault_usdc_to": 15000})
    assert cfg.vault_usdc_to == 15000
    try:
        farm_config({"vault_usdc_from": 100, "vault_usdc_to": 20000})
    except ValueError as exc:
        assert "vault_usdc" in str(exc)
    else:
        raise AssertionError("expected 20k vault to be rejected")
