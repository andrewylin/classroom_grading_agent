"""Handles the one-time OAuth consent flow and token refresh/caching."""
import logging
import os
import time

# Google sometimes returns a granted scope string that differs slightly from
# what was requested (e.g. substituting a narrower, equivalent scope like
# classroom.student-submissions.students.readonly for
# classroom.coursework.students.readonly). oauthlib treats any scope-string
# mismatch as fatal unless told otherwise. Must be set before importing
# google_auth_oauthlib.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config

log = logging.getLogger("google_auth")


def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(config.TOKEN_STORE_PATH):
        creds = Credentials.from_authorized_user_file(config.TOKEN_STORE_PATH, config.SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            for attempt in range(3):
                try:
                    creds.refresh(Request())
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise
                    wait = 2 ** attempt
                    log.warning("Token refresh failed (attempt %d/3); retrying in %s seconds: %s", attempt + 1, wait, exc)
                    time.sleep(wait)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(config.CLIENT_SECRETS_PATH, config.SCOPES)
            # run_local_server opens your browser for the one-time consent screen.
            creds = flow.run_local_server(port=0)
        with open(config.TOKEN_STORE_PATH, "w") as f:
            f.write(creds.to_json())

    return creds
