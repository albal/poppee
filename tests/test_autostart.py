import plistlib

from poppee.autostart import LinuxAutostart, MacAutostart, WindowsAutostart, launch_command

CMD = ["/opt/My Apps/poppee", "run"]


def test_linux_desktop_entry(tmp_path):
    a = LinuxAutostart(config_home=tmp_path)
    assert not a.is_enabled()
    path = a.enable(CMD)
    assert a.is_enabled()
    text = (tmp_path / "autostart" / "poppee.desktop").read_text()
    assert path.endswith("poppee.desktop")
    assert 'Exec="/opt/My Apps/poppee" run' in text
    assert a.disable() and not a.is_enabled() and not a.disable()


def test_linux_quoting():
    assert LinuxAutostart._quote('a"b$c') == '"a\\"b\\$c"'
    assert LinuxAutostart._quote("plain") == "plain"


def test_macos_launch_agent(tmp_path):
    a = MacAutostart(home=tmp_path)
    a.enable(CMD)
    data = plistlib.loads(a.path.read_bytes())
    assert data["ProgramArguments"] == CMD and data["RunAtLoad"] is True
    assert a.is_enabled() and a.disable() and not a.is_enabled()


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    def CreateKey(self, root, key):  # noqa: N802 - mirrors winreg
        return FakeKey()

    def OpenKey(self, root, key, *args):  # noqa: N802
        return FakeKey()

    def SetValueEx(self, key, name, reserved, typ, value):  # noqa: N802
        self.values[name] = value

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_windows_run_key():
    reg = FakeWinreg()
    a = WindowsAutostart(winreg=reg)
    assert not a.is_enabled()
    a.enable(CMD)
    assert reg.values["Poppee"] == '"/opt/My Apps/poppee" run'
    assert a.is_enabled() and a.disable() and not a.disable()


def test_launch_command_runs_the_tray():
    cmd = launch_command()
    assert cmd[-1] == "run"
