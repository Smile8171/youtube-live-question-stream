## Project
- GitHub Actions runs the one-hour YouTube stream daily at 13:30 UTC (19:00 Asia/Kolkata).
- Generate one family-friendly question with Gemini, generate a matching high-quality vertical 9:16 image with Gemini featuring an adult woman host, overlay the exact question legibly using Pillow, and stream it with FFmpeg for one hour.
- Retry Gemini generation and FFmpeg startup with backoff; start the one-hour timer only after the RTMP connection remains alive for 30 seconds. GitHub Actions hard-stops at its six-hour job limit.
- Do not run Render and GitHub Actions stream jobs at the same time; they may compete for the same YouTube stream key.

## Secrets And Safety
- Read credentials only from `GEMINI_API_KEY` and `YOUTUBE_STREAM_KEY` environment variables.
- Never commit `.env` files, real credentials, or stream keys. `.env.example` contains placeholders only.
- Never start a real stream or use real credentials unless the user explicitly asks.

## Development
- Keep changes focused and consistent with the existing Python style.
- Validate Python syntax and deployment configuration after relevant edits when tooling is available.
- Keep `README.md` aligned with actual workflow behavior, GitHub secrets, and scheduling.
