## Project
- GitHub Actions runs the one-hour YouTube stream daily at 13:30 UTC (19:00 Asia/Kolkata).
- Generate one family-friendly question with Gemini, generate a matching high-quality vertical 9:16 image with Gemini featuring an adult woman host, overlay the exact question legibly using Pillow, and stream it with FFmpeg for one hour.
- Use YouTube Live Streaming API OAuth to create a public Education broadcast, bind the existing reusable stream, enable API auto-start/auto-stop, and wait until YouTube reports the broadcast live for 30 seconds before starting the one-hour timer.
- Retry Gemini generation and FFmpeg/API startup with backoff. GitHub Actions hard-stops at its six-hour job limit.
- Do not run Render and GitHub Actions stream jobs at the same time; they may compete for the same YouTube stream key.

## Secrets And Safety
- Read credentials only from `GEMINI_API_KEY`, `YOUTUBE_STREAM_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` environment variables.
- Never commit `.env` files, OAuth client JSON, real credentials, refresh tokens, or stream keys. `.env.example` contains placeholders only.
- Never start a real stream or use real credentials unless the user explicitly asks.

## Development
- Keep changes focused and consistent with the existing Python style.
- Validate Python syntax and deployment configuration after relevant edits when tooling is available.
- Keep `README.md` aligned with actual workflow behavior, GitHub secrets, and scheduling.
