from pathlib import Path

from conftest import FakeClient, RecordingNotifier, make_message

from poppee.checker import AccountResult, Checker, build_notifications
from poppee.config import Account, Config
from poppee.gmail import AuthError
from poppee.state import State

ACCOUNT = Account(email="me@gmail.com", name="Forums")


def make_checker(tmp_path, clients, now=5000.0, **config_kwargs):
    cfg = Config(
        client_secret_file=Path("x"),
        accounts=[Account(email=e, name=e.split("@")[0]) for e in clients]
        if isinstance(clients, dict)
        else [ACCOUNT],
        **config_kwargs,
    )
    lookup = clients if isinstance(clients, dict) else {ACCOUNT.email: clients}
    notifier = RecordingNotifier()
    checker = Checker(
        cfg,
        State(tmp_path / "state.json"),
        notifier,
        client_factory=lambda a: lookup[a.email],
        clock=lambda: now,
    )
    return checker, notifier


def test_first_check_does_not_notify_existing_mail(tmp_path):
    client = FakeClient([make_message("2"), make_message("1")])
    checker, notifier = make_checker(tmp_path, client)
    (result,) = checker.check_all()
    assert result.unread == 2 and result.new == [] and not result.error
    assert [m.id for m in result.recent] == ["2", "1"]
    assert notifier.sent == []


def test_new_mail_is_notified_once(tmp_path):
    client = FakeClient([make_message("1")])
    checker, notifier = make_checker(tmp_path, client)
    checker.check_all()

    client.inbox.insert(0, make_message("2", ts=6000))
    (result,) = checker.check_all()
    assert [m.id for m in result.new] == ["2"]
    assert len(notifier.sent) == 1
    assert "Subject 2" in notifier.sent[0].body
    assert notifier.sent[0].url.endswith("#all/t2")

    checker.check_all()
    assert len(notifier.sent) == 1  # not repeated


def test_state_survives_restart(tmp_path):
    client = FakeClient([make_message("1")])
    make_checker(tmp_path, client)[0].check_all()
    client.inbox.insert(0, make_message("2", ts=6000))
    checker, notifier = make_checker(tmp_path, client)  # fresh process, same state file
    checker.check_all()
    assert len(notifier.sent) == 1
    # Cached metadata is reused rather than refetched.
    assert client.fetched.count("1") == 1


def test_old_mail_scrolling_into_view_is_not_new(tmp_path):
    client = FakeClient([make_message("1")])
    checker, notifier = make_checker(tmp_path, client)
    checker.check_all()
    client.inbox.append(make_message("0", ts=10))  # older than the first check
    (result,) = checker.check_all()
    assert result.new == [] and notifier.sent == []


def test_notify_existing_on_start(tmp_path):
    client = FakeClient([make_message("1")])
    checker, notifier = make_checker(tmp_path, client, notify_existing_on_start=True)
    checker.check_all()
    assert len(notifier.sent) == 1


def test_summary_when_many_new(tmp_path):
    client = FakeClient()
    checker, notifier = make_checker(tmp_path, client, max_notifications=2)
    checker.check_all()
    client.inbox = [make_message(str(i), ts=6000 + i) for i in range(10, 0, -1)]
    checker.check_all()
    assert len(notifier.sent) == 1
    assert notifier.sent[0].title.startswith("10 new messages")
    assert "and 5 more" in notifier.sent[0].body
    assert notifier.sent[0].url.endswith("#inbox")


def test_notifications_disabled(tmp_path):
    client = FakeClient()
    checker, notifier = make_checker(tmp_path, client, notifications=False)
    checker.check_all()
    client.inbox = [make_message("1", ts=6000)]
    assert checker.check_all()[0].new
    assert notifier.sent == []


def test_errors_are_isolated_per_account(tmp_path):
    good = FakeClient([make_message("1")])
    bad = FakeClient(error=AuthError("token revoked"))
    checker, _ = make_checker(tmp_path, {"good@gmail.com": good, "bad@gmail.com": bad})
    results = {r.account.email: r for r in checker.check_all()}
    assert results["good@gmail.com"].unread == 1 and not results["good@gmail.com"].error
    assert "Sign-in needed" in results["bad@gmail.com"].error
    state = State(tmp_path / "state.json").data["accounts"]
    assert state["bad@gmail.com"]["error"]


def test_unexpected_exception_does_not_crash(tmp_path):
    class Boom(FakeClient):
        def unread_ids(self, query, limit=100):
            raise ValueError("kaboom")

    checker, _ = make_checker(tmp_path, Boom())
    (result,) = checker.check_all()
    assert result.error == "ValueError: kaboom"


def test_changing_query_resets_baseline(tmp_path):
    client = FakeClient([make_message("1")])
    checker, notifier = make_checker(tmp_path, client)
    checker.check_all()
    checker.config = Config(
        client_secret_file=Path("x"),
        accounts=[Account(email=ACCOUNT.email, name="Forums", query="label:other")],
    )
    client.inbox.insert(0, make_message("2", ts=6000))
    checker.check_all()
    assert notifier.sent == []


def test_removed_accounts_are_pruned(tmp_path):
    checker, _ = make_checker(tmp_path, FakeClient())
    checker.state.account("gone@gmail.com")["unread"] = 3
    checker.check_all()
    assert "gone@gmail.com" not in State(tmp_path / "state.json").data["accounts"]


def test_build_notifications_trims_long_text():
    long = make_message("1", sender="S" * 200, subject="x" * 500)
    (n,) = build_notifications(AccountResult(ACCOUNT, new=[long]), max_individual=3)
    assert len(n.title) <= 80 and len(n.body) <= 240
    assert build_notifications(AccountResult(ACCOUNT, new=[long]), max_individual=0)[0].title == (
        "1 new messages · Forums"
    )
