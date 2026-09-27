import json

import pytest
from conftest import FakeClient, make_message

from poppee import __version__, cli, config, paths


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_init_creates_config_and_installs_secret(tmp_path, capsys):
    secret = tmp_path / "downloaded.json"
    secret.write_text('{"installed": {}}')
    assert cli.main(["init", "--client-secret", str(secret)]) == 0
    assert paths.config_file().exists()
    assert (paths.config_dir() / "client_secret.json").read_text() == '{"installed": {}}'
    assert "add-account" in capsys.readouterr().out


def test_init_without_secret_prints_next_steps(capsys):
    assert cli.main(["init"]) == 0
    assert "Next steps" in capsys.readouterr().out


def test_list_and_remove(capsys):
    cli.main(["init"])
    config.append_account(paths.config_file(), "a@gmail.com", name="Alpha")
    assert cli.main(["list"]) == 0
    assert "Alpha <a@gmail.com>" in capsys.readouterr().out
    assert cli.main(["remove-account", "a@gmail.com"]) == 0
    assert config.load(paths.config_file()).accounts == []
    assert cli.main(["remove-account", "a@gmail.com"]) == 1


def test_bad_config_exits_with_message():
    paths.config_file().parent.mkdir(parents=True)
    paths.config_file().write_text("poll_interval = 1\n")
    with pytest.raises(SystemExit, match="poll_interval"):
        cli.main(["list"])


def test_check_json_does_not_consume_notifications(monkeypatch, capsys):
    cli.main(["init"])
    config.append_account(paths.config_file(), "a@gmail.com")
    client = FakeClient([make_message("1")])
    monkeypatch.setattr("poppee.checker.default_client_factory", lambda a: client)
    capsys.readouterr()
    assert cli.main(["check", "--json"]) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["unread"] == 1 and entry["recent"][0]["id"] == "1"
    assert not paths.state_file().exists()  # read-only state


def test_config_path(capsys):
    assert cli.main(["config", "--all"]) == 0
    out = capsys.readouterr().out
    assert str(paths.config_file()) in out and "tokens" in out


def test_autostart_status(monkeypatch, capsys):
    class Fake:
        def is_enabled(self):
            return False

    monkeypatch.setattr("poppee.autostart.get_autostart", lambda: Fake())
    assert cli.main(["autostart", "status"]) == 0
    assert capsys.readouterr().out.strip() == "disabled"
