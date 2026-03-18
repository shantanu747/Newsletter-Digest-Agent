"""One-time OAuth 2.0 consent flow for Gmail API access.

Run this script once to generate the token.json file that the agent uses
to authenticate with Gmail on every subsequent run.

Usage:
    python scripts/gmail_auth.py
"""

from __future__ import annotations

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> None:
    token_path = os.environ.get("GMAIL_OAUTH_TOKEN_PATH", "token.json")
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    if not os.path.exists(creds_path):
        print(
            f"ERROR: '{creds_path}' not found.\n"
            "\n"
            "Download credentials.json from Google Cloud Console > APIs & Services >"
            " Credentials > OAuth 2.0 Client IDs\n"
            "\n"
            "Steps:\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. Navigate to APIs & Services > Credentials\n"
            "  3. Click on your OAuth 2.0 Client ID (Desktop app type)\n"
            "  4. Click 'Download JSON' and save it as credentials.json\n"
            "  5. Re-run this script\n"
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    credentials = flow.run_local_server(port=0)

    with open(token_path, "w") as token_file:
        token_file.write(credentials.to_json())

    print(f"Authentication successful! Token saved to: {token_path}")
    print(
        "You can now run the Newsletter Digest Agent. "
        f"Set GMAIL_OAUTH_TOKEN_PATH={token_path} in your .env file."
    )


if __name__ == "__main__":
    main()
