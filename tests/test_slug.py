from plugin.wager_bot.slug import SLUG_RE, alternate_slug, slug_from_email


def test_slug_from_simple_email() -> None:
    assert slug_from_email("fallex@example.com") == "fallex"
    assert SLUG_RE.fullmatch("fallex")


def test_slug_strips_plus_and_dots() -> None:
    value = slug_from_email("john.doe+tag@gmail.com")
    assert value == "johndoe"
    assert SLUG_RE.fullmatch(value)


def test_short_local_part_uses_address() -> None:
    value = slug_from_email("ab@x.com", "0xDcD4bE7cA9F02AE6F6B96904754D817942d40566")
    assert SLUG_RE.fullmatch(value)
    assert len(value) >= 3


def test_alternate_slug_is_valid() -> None:
    value = alternate_slug("fallex", "0xDcD4bE7cA9F02AE6F6B96904754D817942d40566")
    assert SLUG_RE.fullmatch(value)
    assert value != "fallex"
