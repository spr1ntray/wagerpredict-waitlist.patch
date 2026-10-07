from plugin.wager_bot.options import run_config


def test_register_pause_defaults() -> None:
    cfg = run_config({})
    assert cfg.pause_from_ms == 400
    assert cfg.pause_to_ms == 1200


def test_register_rejects_inverted_pause() -> None:
    try:
        run_config({"pause_from_ms": 2000, "pause_to_ms": 100})
    except ValueError as err:
        assert "pause_range" in str(err)
    else:
        raise AssertionError("expected inverted pause to fail")


def test_register_accepts_zero_pause() -> None:
    cfg = run_config({"pause_from_ms": 0, "pause_to_ms": 0})
    assert cfg.pause_from_ms == 0
    assert cfg.pause_to_ms == 0


def test_pause_out_of_range() -> None:
    try:
        run_config({"pause_from_ms": 0, "pause_to_ms": 9000})
    except ValueError as err:
        assert "pause_to_ms_range" in str(err)
    else:
        raise AssertionError("expected oversize pause to fail")
