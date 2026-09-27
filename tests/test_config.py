import tomllib

import pytest

from poppee import config
from poppee.config import ConfigError


def test_template_is_valid_and_has_defaults(tmp_path):
    path = tmp_path / "config.toml"
    assert config.write_template(path)
    assert not config.write_template(path)  # never overwrites
    cfg = config.load(path)
    assert cfg.accounts == []
    assert cfg.poll_interval == 120
    assert cfg.client_secret_file == tmp_path / "client_secret.json"
    assert cfg.path == path


def test_missing_file_has_helpful_error(tmp_path):
    with pytest.raises(ConfigError, match="poppee init"):
        config.load(tmp_path / "nope.toml")


def test_parse_accounts(tmp_path):
    cfg = config.parse(
        {
            "client_secret_file": "/abs/secret.json",
            "accounts": [
                {"email": "a@gmail.com"},
                {"email": "b@gmail.com", "name": "B", "query": "label:x", "notify": False},
            ],
        },
        base_dir=tmp_path,
    )
    a, b = cfg.accounts
    assert a.name == "a@gmail.com" and a.query == config.DEFAULT_QUERY and a.notify
    assert b.name == "B" and b.query == "label:x" and not b.notify
    assert cfg.find_account("B@GMAIL.COM") is b
    assert str(cfg.client_secret_file).endswith("secret.json")


@pytest.mark.parametrize(
    "data, message",
    [
        ({"poll_interval": 5}, "at least"),
        ({"poll_interval": True}, "int"),
        ({"notifications": "yes"}, "bool"),
        ({"bogus": 1}, "Unknown"),
        ({"accounts": [{"name": "x"}]}, "email"),
        ({"accounts": [{"email": "a@x.com"}, {"email": "A@x.com"}]}, "more than once"),
        ({"accounts": [{"email": "a@x.com", "colour": "red"}]}, "unknown"),
        ({"accounts": [{"email": "a@x.com", "query": "  "}]}, "empty"),
        ({"max_notifications": -1}, "negative"),
    ],
)
def test_validation_errors(tmp_path, data, message):
    with pytest.raises(ConfigError, match=message):
        config.parse(data, base_dir=tmp_path)


def test_append_and_remove_account(tmp_path):
    path = tmp_path / "config.toml"
    config.write_template(path)
    config.append_account(path, "one@gmail.com", name='Quote "me"')
    config.append_account(path, "two@gmail.com", query="is:unread label:forums")
    config.append_account(path, "three@gmail.com")
    cfg = config.load(path)
    assert [a.email for a in cfg.accounts] == ["one@gmail.com", "two@gmail.com", "three@gmail.com"]
    assert cfg.accounts[0].name == 'Quote "me"'
    assert cfg.accounts[1].query == "is:unread label:forums"

    assert config.remove_account(path, "TWO@gmail.com")
    assert not config.remove_account(path, "missing@gmail.com")
    cfg = config.load(path)
    assert [a.email for a in cfg.accounts] == ["one@gmail.com", "three@gmail.com"]
    # The comments in the template survive editing.
    assert "poll_interval" in path.read_text()
    tomllib.loads(path.read_text())
