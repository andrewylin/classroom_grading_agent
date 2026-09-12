"""Handles the one-time OAuth consent flow and token refresh/caching."""
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config


def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(config.TOKEN_STORE_PATH):
        creds = Credentials.from_authorized_user_file(config.TOKEN_STORE_PATH, config.SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(config.CLIENT_SECRETS_PATH, config.SCOPES)
            # run_local_server opens your browser for the one-time consent screen.
            creds = flow.run_local_server(port=0)
        with open(config.TOKEN_STORE_PATH, "w") as f:
            f.write(creds.to_json())

    return creds
