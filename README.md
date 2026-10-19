# YouTube Live Question Stream

GitHub Actions runs the job every day at 19:00 India time. The job asks Gemini for one family-friendly question, generates a matching high-quality 9:16 image featuring an adult woman host, overlays the question in a legible display font, and streams the vertical image with silent audio to YouTube Live for one hour using FFmpeg.

## Requirements

- Python 3.12 or newer
- FFmpeg installed and available on `PATH`
- A Gemini API key
- A YouTube Live stream key
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
python main.py --duration-seconds 3600
```

Keep the terminal open while testing. Stop the worker with Ctrl+C. Never commit real keys or put them in `.env.example`.

## Automate With GitHub Actions

1. Push this repository to GitHub and make sure GitHub Actions are enabled.
2. In the repository, open **Settings > Secrets and variables > Actions** and add `GEMINI_API_KEY` and `YOUTUBE_STREAM_KEY` as repository secrets. Never put real keys in source files.
3. In YouTube Studio's Live Control Room, configure the matching stream key and enable **Auto-start** and **Auto-stop** in Stream settings. This is a one-time setup so YouTube starts when FFmpeg connects and ends when FFmpeg disconnects.
4. The workflow in `.github/workflows/daily-live.yml` starts at 13:30 UTC, which is 7:00 PM in India. Check the **Actions** tab for run logs.

If question or image generation fails, or FFmpeg cannot connect, the job retries with increasing delays. The one-hour live timer begins only after FFmpeg stays connected for 30 seconds. GitHub cancels any job after its six-hour maximum, so repeated failures beyond that limit still need attention in the **Actions** tab. YouTube must have Auto-start/Auto-stop enabled for the incoming stream to become a broadcast and end when FFmpeg disconnects.

GitHub scheduled workflows can be delayed during busy periods, so 7:00 PM is the requested schedule, not a guaranteed exact start time.

Standard GitHub-hosted runner minutes are free for public repositories. GitHub Free private repositories include 2,000 runner minutes per month; one hour every day uses about 1,800 minutes for streaming alone, and setup time also counts, so the monthly limit may be exceeded. Public repositories expose source code, but GitHub Actions secrets are not exposed to viewers. Gemini image generation may have separate API charges depending on your account's quota and billing.

Do not run the Render Background Worker at the same time as this workflow; it is a separate paid path and could send a second stream using the same key. The `render.yaml` and Dockerfile are retained for that alternative deployment only.

## Configuration

- `GEMINI_API_KEY`: required Gemini API key
- `YOUTUBE_STREAM_KEY`: required YouTube Live stream key
- `GEMINI_MODEL`: optional Gemini model name; defaults to `gemini-2.5-flash`
- `GEMINI_IMAGE_MODEL`: optional Gemini image model; defaults to `gemini-3.1-flash-image`
- `LOG_LEVEL`: optional Python logging level; defaults to `INFO`

Revoke and replace a stream key immediately if it is exposed.