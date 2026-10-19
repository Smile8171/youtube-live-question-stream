from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize YouTube Live automation")
    parser.add_argument(
        "--client-secrets",
        default="client_secret.json",
        help="Path to the downloaded Google OAuth Desktop client JSON",
    )
    arguments = parser.parse_args()
    client_secrets = Path(arguments.client_secrets)
    if not client_secrets.is_file():
        raise SystemExit(f"OAuth client file not found: {client_secrets}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets),
        scopes=[YOUTUBE_SCOPE],
    )
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise SystemExit("Google returned no refresh token; revoke the app grant and authorize again.")

    print("Add these values as GitHub Actions repository secrets:")
    print(f"YOUTUBE_CLIENT_ID={credentials.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={credentials.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={credentials.refresh_token}")


if __name__ == "__main__":
    main()