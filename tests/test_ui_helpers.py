"""Tests for the display logic of the tray and preview window (no GUI needed)."""

from conftest import make_message

from poppee.checker import AccountResult
from poppee.config import Account
from poppee.icon import render_icon
from poppee.preview import as_text, format_age, load_sections
from poppee.state import State
from poppee.tray import account_label, tooltip

A = Account(email="a@gmail.com", name="Alpha")
B = Account(email="b@gmail.com", name="Beta")


def test_tooltip_and_labels():
    ok = AccountResult(A, unread=3, more=True)
    bad = AccountResult(B, error="Sign-in needed: token revoked")
    assert tooltip([ok, bad]) == "Poppee: 3 unread, 1 with problems"
    assert tooltip([]) == "Poppee: no accounts"
    assert account_label(ok) == "Alpha: 3+ unread"
    assert account_label(bad).startswith("⚠ Beta: Sign-in needed")
    assert len(tooltip([AccountResult(A, error="x")] * 50)) <= 63


def test_render_icon():
    for count in (0, 7, 42, 1234):
        img = render_icon(count, size=64)
        assert img.size == (64, 64) and img.mode == "RGBA"
    assert render_icon(0, size=64).tobytes() != render_icon(5, size=64).tobytes()


def test_format_age():
    assert format_age(100, now=130) == "now"
    assert format_age(0, now=300) == "5m"
    assert format_age(0, now=7200) == "2h"
    assert format_age(0, now=86400 * 3) == "3d"
    assert format_age(0, now=86400 * 15) == "2w"


def test_preview_reads_state(tmp_path):
    state = State(tmp_path / "state.json")
    st = state.account("a@gmail.com")
    st.update(name="Alpha", email="a@gmail.com", unread=1, recent=[make_message("1").to_dict()])
    state.save()
    (section,) = load_sections(tmp_path / "state.json")
    assert section.name == "Alpha" and section.messages[0].id == "1"
    text = as_text([section])
    assert "Alpha <a@gmail.com> - 1 unread" in text and "Subject 1" in text
    assert "poppee run" in as_text([])


def test_corrupt_state_is_ignored(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    assert load_sections(tmp_path / "state.json") == []
