# YouTube Live Question Stream

GitHub Actions runs the job every day at 19:00 India time. The job asks Gemini for one family-friendly question, generates a matching high-quality 9:16 image featuring an adult woman host, overlays the question in a legible display font, creates a public YouTube broadcast through the Live Streaming API, and streams the vertical image with silent audio for one hour using FFmpeg.

## Requirements

- Python 3.12 or newer
- FFmpeg installed and available on `PATH`
- A Gemini API key
- A YouTube Live stream key
- YouTube Data API v3 enabled in a Google Cloud project
- Google OAuth client ID, client secret, and refresh token for the channel owner
- A GitHub repository with Actions enabled

## Run Locally

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set the two required environment variables in PowerShell, then launch the worker:

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
$env:YOUTUBE_STREAM_KEY = "your-youtube-stream-key"
$env:YOUTUBE_CLIENT_ID = "your-oauth-client-id"
$env:YOUTUBE_CLIENT_SECRET = "your-oauth-client-secret"
$env:YOUTUBE_REFRESH_TOKEN = "your-youtube-refresh-token"
python main.py --duration-seconds 3600
```

Keep the terminal open while testing. Stop the worker with Ctrl+C. Never commit real keys or put them in `.env.example`.

## Automate With GitHub Actions

1. Push this repository to GitHub and make sure GitHub Actions are enabled.
2. In Google Cloud Console, create a project, enable **YouTube Data API v3**, configure the OAuth consent screen, and create an OAuth client of type **Desktop app**.
3. Download the OAuth client JSON to this project directory as `client_secret.json`. Keep it local; `.gitignore` excludes client secret JSON files.
4. Install requirements locally, then run `python authorize_youtube.py`. Sign in to the channel owner account and approve YouTube access. The script prints the client ID, client secret, and refresh token. Add these as the `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` GitHub repository secrets.
5. Add `GEMINI_API_KEY` and `YOUTUBE_STREAM_KEY` as GitHub repository secrets too. Never paste credentials into source files, issues, or chat.
6. The workflow in `.github/workflows/daily-live.yml` starts at 13:30 UTC, which is 7:00 PM in India. Check the **Actions** tab for run logs.

Each run finds the existing reusable YouTube stream by matching `YOUTUBE_STREAM_KEY`, creates a new public Education broadcast, binds the stream, and sets API `enableAutoStart` and `enableAutoStop`. It waits until YouTube reports the broadcast `live` continuously for 30 seconds before counting the one-hour duration. If the broadcast completes early, the worker creates a replacement broadcast and retries. No manual Studio Go Live click is required after OAuth and secrets are configured.

OAuth refresh tokens from an External consent screen left in **Testing** expire after seven days. Set the consent screen to **In production** for ongoing automation; Google may show an unverified-app warning or require verification for the YouTube scope. Keep the OAuth client restricted to your own use and revoke access if the token is exposed.

If question/image generation, API setup, or RTMP publishing fails, the job retries with increasing delays. GitHub cancels jobs at its six-hour maximum, so repeated failures beyond that limit need attention in the **Actions** tab.

GitHub scheduled workflows can be delayed during busy periods, so 7:00 PM is the requested schedule, not a guaranteed exact start time.

Standard GitHub-hosted runner minutes are free for public repositories. GitHub Free private repositories include 2,000 runner minutes per month; one hour every day uses about 1,800 minutes for streaming alone, and setup time also counts, so the monthly limit may be exceeded. Public repositories expose source code, but GitHub Actions secrets are not exposed to viewers. Gemini image generation may have separate API charges depending on your account's quota and billing.

Do not run the Render Background Worker at the same time as this workflow; it is a separate paid path and could send a second stream using the same key. The `render.yaml` and Dockerfile are retained for that alternative deployment only.

## Configuration

- `GEMINI_API_KEY`: required Gemini API key
- `YOUTUBE_STREAM_KEY`: required YouTube Live stream key
- `GEMINI_MODEL`: optional Gemini model name; defaults to `gemini-2.5-flash`
- `GEMINI_IMAGE_MODEL`: optional Gemini image model; defaults to `gemini-3.1-flash-image`
- `YOUTUBE_CLIENT_ID`: required OAuth client ID
- `YOUTUBE_CLIENT_SECRET`: required OAuth client secret
- `YOUTUBE_REFRESH_TOKEN`: required OAuth refresh token for the channel owner
- `LOG_LEVEL`: optional Python logging level; defaults to `INFO`

Revoke and replace a stream key immediately if it is exposed.