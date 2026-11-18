from __future__ import annotations

import json
from pathlib import Path

from tests.helpers import make_config
from voicebridge.cli import main


def test_doctor_json_for_mock_installation(tmp_path: Path, capsys) -> None:
    config = make_config()
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[server]
host = "127.0.0.1"
http_port = {config.server.http_port}
ws_port = {config.server.ws_port}
tcp_port = {config.server.tcp_port}

[transports.websocket]
enabled = true

[transports.tcp]
enabled = true

[asr]
provider = "mock"

[asr.mock]
transcript = "test"

[input]
backend = "null"
""",
        encoding="utf-8",
    )
    code = main(["doctor", "--config", str(path), "--json"])
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["ok"]
    assert all("api" not in item["detail"].lower() for item in output["checks"])


def test_config_output_is_valid_toml(capsys) -> None:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    from voicebridge.cli import main

    code = main(["config", "--config", "config.demo.toml"])
    output = capsys.readouterr().out
    parsed = tomllib.loads(output)
    assert code == 0
    assert parsed["server"]["ws_port"] == 18766
    assert parsed["input"]["backend"] == "null"


def test_doctor_fails_when_required_token_is_empty(tmp_path: Path, capsys) -> None:
    config = make_config(require_token=True, token="")
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[server]
host = "127.0.0.1"
http_port = {config.server.http_port}
ws_port = {config.server.ws_port}
tcp_port = {config.server.tcp_port}
require_token = true
token = ""

[transports.websocket]
enabled = true

[transports.tcp]
enabled = true

[asr]
provider = "mock"

[asr.mock]
transcript = "test"

[input]
backend = "null"
""",
        encoding="utf-8",
    )

    code = main(["doctor", "--config", str(path), "--json"])
    output = json.loads(capsys.readouterr().out)
    token_check = next(item for item in output["checks"] if item["check"] == "token")

    assert code == 1
    assert not output["ok"]
    assert token_check["status"] == "fail"
