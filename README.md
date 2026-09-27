# Poppee

A free, open-source Gmail notifier for people who watch lots of accounts. It's meant as a
PopPeeper replacement.

- **OAuth2 sign-in** through the official Gmail API. No passwords, POP or IMAP.
  Access is **read-only** (`gmail.readonly`).
- **Handles 10+ accounts.** They're checked in parallel, each with its own label and Gmail
  search.
- **Native notifications** on GNOME and other Linux desktops, macOS and Windows 10/11.
  Click a notification to open that message in Gmail.
- **Tray icon** with an unread badge and a per-account menu, plus a **preview popup**
  that lists sender, subject and snippet for recent mail.
- **Easy to set up:** one small TOML file, `poppee add-account` for each account, and
  `poppee autostart enable`.
- **Free:** MIT licensed, no paid tiers, no telemetry. Tokens stay on your computer.

## 1. Install

**Prebuilt binaries** (no Python needed): download the archive for your OS from the
GitHub **Releases** page.

| OS      | File                          | Run                                                     |
|---------|-------------------------------|---------------------------------------------------------|
| Windows | `poppee-X.Y.Z-windows-x64.zip`| unzip, run `poppee.exe` for commands and `poppee-tray.exe` for the app |
| macOS   | `poppee-X.Y.Z-macos-arm64.zip`| unzip, move `Poppee.app` to Applications. For commands use `/Applications/Poppee.app/Contents/MacOS/Poppee` |
| Linux   | `poppee-X.Y.Z-linux-x64.tar.gz`| extract, run `poppee/poppee`                           |

The macOS app isn't signed. The first time, right-click it and choose **Open**, or run
`xattr -dr com.apple.quarantine Poppee.app`.

**With Python 3.11+** (any OS, including Intel Macs):

```bash
pipx install poppee        # or: pip install --user poppee
# or from a checkout:  pipx install .
```

## 2. Create your Google OAuth client (one time, about 5 minutes)

Google doesn't let open-source desktop apps ship a shared Gmail client secret, so you
create your own. It's free.

1. Open <https://console.cloud.google.com/> and **create a project**, for example "Poppee".
2. Go to **APIs & Services → Library**, search for **Gmail API** and click **Enable**.
3. Go to **Google Auth Platform → Branding** (the "OAuth consent screen"). Choose
   **External**, then enter an app name and your email address.
4. Under **Audience**, click **Publish app** so the status is **In production**.
   > ⚠️ In **Testing** status, Google expires sign-ins after **7 days**. Publishing
   > fixes that. Google won't review it, and it works fine for personal use (up to 100 users).
   > At sign-in you'll see *"Google hasn't verified this app"*. Click **Advanced → Go to
   > Poppee** to continue. It's your own app.
5. Under **Clients**, choose **Create client → Application type: Desktop app**, then click
   **Download JSON**.

> **You only do this once, not once per Gmail account.** Create the project in any Google
> account you like. That one client file works for all your accounts: each one is added
> later with a quick `poppee add-account` sign-in. Because the app is published, the
> other accounts don't need to be added as test users. Each account shows the "unverified
> app" screen once, on its first sign-in.

## 3. Configure

```bash
poppee init --client-secret ~/Downloads/client_secret_XXXX.json
poppee add-account --name "Forum alerts"     # a browser opens: pick the account, allow access
poppee add-account --name "Guild"            # repeat for each account
poppee test-notify                           # check that notifications show up
poppee autostart enable                      # start at login
poppee run                                   # start now (same as plain `poppee`)
```

Tip: `poppee add-account --email someone@gmail.com` pre-selects that account on Google's
sign-in page, which helps when your browser is signed in to many accounts.

### The config file

`poppee config` prints where it lives and `poppee config --edit` opens it. After editing,
choose **Reload config** from the tray menu.

```toml
poll_interval = 120            # seconds between checks (minimum 30)
notifications = true
max_notifications = 3          # above this, one summary pop-up per account
notify_existing_on_start = false
click_to_open = true
client_secret_file = "client_secret.json"

[[accounts]]
name = "Forum alerts"
email = "me.forums@gmail.com"

[[accounts]]
name = "Guild"
email = "guild.mail@gmail.com"
query = "is:unread label:guild -from:spam@example.com"   # any Gmail search
notify = false                  # count in the tray only, no pop-ups
enabled = true
```

| Location | Linux | macOS | Windows |
|---|---|---|---|
| config | `~/.config/poppee/` | `~/Library/Application Support/poppee/` | `%LOCALAPPDATA%\poppee\` |
| tokens, state, logs | `~/.local/share/poppee/` | `~/Library/Application Support/poppee/` | `%LOCALAPPDATA%\poppee\` |

You can move both with the `POPPEE_CONFIG_DIR` and `POPPEE_DATA_DIR` environment variables,
for example for a portable install on a USB stick.

## Commands

| Command | What it does |
|---|---|
| `poppee` / `poppee run` | Start the tray app. `--no-tray` gives notifications only |
| `poppee init [--client-secret FILE]` | Create the config and install the OAuth client file |
| `poppee add-account [--name N] [--email E] [--query Q]` | Sign in to an account and add it |
| `poppee remove-account EMAIL` | Remove an account and delete its token |
| `poppee list` | List accounts and whether each is signed in |
| `poppee check [--json] [--notify]` | Check once and print the result |
| `poppee preview [--text]` | Open the recent-mail popup |
| `poppee test-notify` | Show a test notification |
| `poppee config [--edit] [--all]` | Show or edit the config, data and log paths |
| `poppee autostart enable\|disable\|status` | Start at login |

## Platform notes

- **GNOME:** notifications work out of the box through `notify-send`, or D-Bus as a
  fallback. GNOME hides tray icons by default. To see the icon, install the
  **AppIndicator and KStatusNotifierItem Support** extension (preinstalled on Ubuntu) and
  install Poppee with PyGObject available:
  `sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1` followed by
  `pipx install --system-site-packages poppee`. Without a tray, Poppee keeps running and
  still sends notifications.
- **macOS:** notifications come from Notification Center through `osascript`. For
  click-to-open, install `brew install terminal-notifier`. Poppee lives in the menu bar
  and has no Dock icon.
- **Windows:** native toast notifications that open the message when clicked. Use
  `poppee-tray.exe` so no console window appears.

## How it works

For every account, Poppee asks the Gmail API for the ids of messages that match the
account's search. It then fetches headers (From, Subject and a snippet) only for ids it
hasn't seen before. That's roughly one small request per account per check, well inside
Gmail's free quota. On the first check, mail that's already unread is recorded without
notifications, so you aren't flooded. Only the message ids, headers and snippets for the
preview are stored locally, in `state.json`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

Building a standalone app locally:

```bash
pip install -e ".[bundle]"
python packaging/make_icons.py
pyinstaller --noconfirm packaging/poppee.spec    # output in dist/
```

### CI and releases

- `.github/workflows/ci.yml`: lint, then the tests on Linux, macOS and Windows for
  Python 3.11–3.13. It builds the wheel and sdist and does a PyInstaller build with a smoke
  test on every OS.
- `.github/workflows/release.yml`: runs when you push a `vX.Y.Z` tag. It checks that the
  tag matches `poppee.__version__`, runs CI, builds the binaries for all three OSes plus the
  wheel and sdist, and publishes a GitHub Release with checksums. If the repository
  variable `PUBLISH_TO_PYPI` is `true`, it also publishes to PyPI using
  [trusted publishing](https://docs.pypi.org/trusted-publishers/) through an environment
  named `pypi`.

To cut a release:

```bash
# bump __version__ in src/poppee/__init__.py, commit, then:
git tag v0.1.0 && git push origin main v0.1.0
```

## License

MIT
