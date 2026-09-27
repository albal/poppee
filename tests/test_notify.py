import subprocess
import xml.dom.minidom

from poppee.notify import (
    LinuxNotifier,
    LogNotifier,
    MacNotifier,
    Notification,
    WindowsNotifier,
    get_notifier,
)

N = Notification(
    "Forum <admin> & co", "New reply: 'hi' <b>", url="https://mail.google.com/x?a=1&b=2"
)


class Recorder:
    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="")


def which_only(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_linux_notify_send_without_click():
    run = Recorder()
    ok = LinuxNotifier(click_to_open=False, which=which_only("notify-send"), run=run).send(N)
    assert ok
    cmd = run.calls[0][0]
    assert cmd[0] == "notify-send" and "--app-name=Poppee" in cmd
    assert cmd[-2] == N.title
    assert cmd[-1] == "New reply: 'hi' &lt;b&gt;"  # body is markup-escaped


def test_linux_notify_send_with_click_action():
    run = Recorder(stdout="Usage:\n  -A, --action=[NAME=]Text...")
    started = []

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            started.append(cmd)

        def communicate(self):
            return ("", "")

    notifier = LinuxNotifier(which=which_only("notify-send"), run=run, popen=FakeProc)
    assert notifier.send(N)
    assert "--wait" in started[0] and "--action=default=Open" in started[0]


def test_linux_falls_back_to_gdbus():
    run = Recorder()
    assert LinuxNotifier(which=which_only("gdbus"), run=run).send(N)
    cmd = run.calls[0][0]
    assert cmd[:2] == ["gdbus", "call"]
    assert '"Forum <admin> & co"' in cmd


def test_linux_no_tools():
    assert not LinuxNotifier(which=which_only()).send(N)


def test_linux_failure_is_reported():
    run = Recorder(returncode=1)
    assert not LinuxNotifier(click_to_open=False, which=which_only("notify-send"), run=run).send(N)


def test_macos_osascript_passes_text_as_arguments():
    run = Recorder()
    assert MacNotifier(which=which_only(), run=run).send(N)
    cmd = run.calls[0][0]
    assert cmd[0] == "osascript" and cmd[-2:] == [N.title, N.body]


def test_macos_terminal_notifier_opens_url():
    run = Recorder()
    assert MacNotifier(which=which_only("terminal-notifier"), run=run).send(N)
    cmd = run.calls[0][0]
    assert cmd[cmd.index("-open") + 1] == N.url


def test_windows_toast_xml_is_well_formed():
    run = Recorder()
    notifier = WindowsNotifier(run=run)
    assert notifier.send(N)
    cmd, kwargs = run.calls[0]
    assert cmd[0] == "powershell.exe"
    toast = kwargs["env"]["POPPEE_TOAST_XML"]
    doc = xml.dom.minidom.parseString(toast)
    root = doc.documentElement
    assert root.getAttribute("launch") == N.url
    texts = [t.firstChild.data for t in doc.getElementsByTagName("text")]
    assert texts[:2] == [N.title, N.body]


def test_windows_toast_without_url():
    xml_text = WindowsNotifier().toast_xml(Notification("t", "b"))
    assert "launch" not in xml_text


def test_get_notifier_per_platform():
    assert get_notifier(platform="win32").name == "windows"
    assert get_notifier(platform="darwin").name == "macos"
    assert get_notifier(platform="linux").name == "linux"
    assert isinstance(get_notifier(platform="plan9"), LogNotifier)
