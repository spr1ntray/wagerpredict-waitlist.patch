import json
from pathlib import Path


def _manifest() -> dict:
    path = Path(__file__).resolve().parents[1] / "wagerpredict-testnet" / "hub.plugin.json"
    return json.loads(path.read_text())


def test_contract_and_catalog() -> None:
    manifest = _manifest()
    assert manifest["name"] == "Wager"
    assert manifest["presentation"]["display_name"] == "Wager"
    assert manifest["version"] == "1.24.0"
    assert "очеред" in manifest["presentation"]["description"].lower()
    assert "почт" in manifest["presentation"]["description"].lower()
    assert "testnet" not in manifest["presentation"]["description"].lower()
    assert len(manifest["presentation"]["description"]) <= 4000
    assert len(manifest["description"]) <= 500
    assert manifest["contract_version"] == "SH-SOFTWARE-0.6/4"
    assert manifest["catalog"]["sections"] == ["general"]
    assert manifest["compatibility"]["hub"] == ">=0.6.15"
    risks = {action["risk"] for action in manifest["actions"]}
    assert risks == {"external_write", "read"}
    assert "testnet_write" not in risks
    assert "mainnet_write" not in risks
    assert manifest["permissions"]["financial_risk"] == "none"
    assert manifest["permissions"]["chains"] == []
    assert manifest["permissions"]["browser"] is False
    assert manifest["permissions"]["local_services"] == []
    assert manifest["permissions"]["network"] == [
        "api.predictprotocol.app",
        "wagerpredict.com",
    ]
    assert manifest["permissions"]["secrets"] == ["evm_private_key", "proxy", "email"]
    assert manifest["actions"][0]["id"] == "register"


def test_register_is_external_write() -> None:
    register = next(action for action in _manifest()["actions"] if action["id"] == "register")
    assert register["risk"] == "external_write"
    assert register["account_mode"] == "one_or_more"
    assert "referral" not in register
    assert register["permissions"]["secrets"] == ["evm_private_key", "proxy", "email"]
    assert register["resources"]["account"] == ["private_key", "proxy", "email"]
    assert register["resources"]["settings"] == []
    keys = register["options"]["properties"].keys()
    assert "referral_code" not in keys
    assert "referrer_code" not in keys
    assert "invite" not in keys
    assert "account_concurrency" in keys
    assert "account_concurrency" not in register["options"]["required"]
    conc = register["options"]["properties"]["account_concurrency"]
    assert conc["minimum"] == 1
    assert conc["maximum"] == 8
    assert conc["multipleOf"] == 1
    assert isinstance(conc["default"], int)
    assert 1 <= conc["default"] <= 8
    pause_from = register["options"]["properties"]["pause_from_ms"]
    pause_to = register["options"]["properties"]["pause_to_ms"]
    assert pause_from["default"] <= pause_to["default"]
    assert pause_from["x-ui"]["range"]["id"] == pause_to["x-ui"]["range"]["id"]
    for name, prop in register["options"]["properties"].items():
        assert "title" in prop, name
        assert "description" in prop, name
        assert "x-ui" in prop, name
        if prop.get("type") == "string" and "enum" not in prop:
            assert "maxLength" in prop, name
        ui = prop.get("x-ui") or {}
        if ui.get("control") not in {"slider", "dual_range"}:
            continue
        step = int(prop.get("multipleOf") or 1)
        steps = (int(prop["maximum"]) - int(prop["minimum"])) // step
        assert 1 <= steps <= 1000, name


def test_requirements_are_http_only() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "wagerpredict-testnet" / "requirements.txt"
    ).read_text()
    assert "eth-account" in text
    assert "requests" in text
    assert "playwright" not in text
    assert "web3" not in text
    assert "websocket-client" not in text


def test_inspect_is_read_only() -> None:
    inspect = next(action for action in _manifest()["actions"] if action["id"] == "inspect")
    assert inspect["risk"] == "read"
    assert inspect["permissions"]["secrets"] == ["proxy"]
    assert inspect["resources"]["account"] == ["proxy"]
    assert inspect["output"]["primary_kind"] == "account_snapshot"
    keys = {col["key"] for col in inspect["output"]["columns"]}
    assert keys == {"allowed", "requested", "queue_status"}
    assert "slug" not in keys
    assert "email" not in keys
    conc = inspect["options"]["properties"]["account_concurrency"]
    assert conc["minimum"] == 1
    assert conc["maximum"] == 10
    assert conc["multipleOf"] == 1
