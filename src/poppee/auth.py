"""OAuth2 sign-in and token storage."""

from __future__ import annotations

import os
import re
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from . import paths

# Read-only access is all a notifier needs.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class AuthSetupError(Exception):
    """OAuth is not set up (e.g. client_secret.json is missing)."""


def token_file(email: str) -> Path:
    safe = re.sub(r"[^a-z0-9._@+-]", "_", email.lower())
    return paths.tokens_dir() / f"{safe}.json"


def has_token(email: str) -> bool:
    return token_file(email).exists()


def load_credentials(email: str) -> Credentials | None:
    path = token_file(email)
    if not path.exists():
        return None
    return Credentials.from_authorized_user_file(str(path), SCOPES)


def save_credentials(email: str, creds: Credentials) -> Path:
    path = token_file(email)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Tokens grant read access to the mailbox: keep them private to this user.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    return path


def delete_credentials(email: str) -> bool:
    path = token_file(email)
    if path.exists():
        path.unlink()
        return True
    return False


def authorize(client_secret_file: Path, login_hint: str | None = None) -> Credentials:
    """Run the browser sign-in flow and return fresh credentials."""
    if not client_secret_file.exists():
        raise AuthSetupError(
            f"OAuth client file not found: {client_secret_file}\n"
            "Create a 'Desktop app' OAuth client in Google Cloud Console, download its JSON "
            "and run `poppee init --client-secret <file>` (see README)."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
    extra = {"prompt": "select_account consent"}
    if login_hint:
        extra["login_hint"] = login_hint
    return flow.run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message="Opening your browser to sign in to Google.\n"
        "If it does not open, visit this URL:\n{url}",
        success_message="Poppee is now authorized. You can close this tab.",
        **extra,
    )


def session_for(email: str) -> AuthorizedSession:
    creds = load_credentials(email)
    if creds is None:
        from .gmail import AuthError

        raise AuthError(f"not signed in - run `poppee add-account --email {email}`")
    return AuthorizedSession(creds)
