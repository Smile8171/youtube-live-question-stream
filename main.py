from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from PIL import Image, ImageDraw, ImageFont

LOG = logging.getLogger("youtube_live")
IMAGE_PATH = Path("question.png")
STOP = threading.Event()
WIDTH, HEIGHT = 1080, 1920


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def create_youtube_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=required_env("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=required_env("YOUTUBE_CLIENT_ID"),
        client_secret=required_env("YOUTUBE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/youtube"],
    )
    credentials.refresh(Request())
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def find_stream_for_key(youtube, stream_key: str) -> dict[str, str]:
    page_token = None
    while True:
        response = youtube.liveStreams().list(
            part="id,snippet,cdn",
            mine=True,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for stream in response.get("items", []):
            stream_name = stream.get("cdn", {}).get("ingestionInfo", {}).get("streamName")
            if stream_name == stream_key:
                return {
                    "id": stream["id"],
                    "ingestion_url": stream["cdn"]["ingestionInfo"]["ingestionAddress"],
                }
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    raise RuntimeError("YOUTUBE_STREAM_KEY was not found among streams owned by the authorized channel")


def create_live_broadcast(youtube, stream_id: str, question: str) -> str:
    local_date = datetime.now().astimezone().strftime("%d %b %Y")
    response = youtube.liveBroadcasts().insert(
        part="snippet,status,contentDetails",
        body={
            "snippet": {
                "title": f"Daily Question Quiz | {local_date}",
                "description": f"One family-friendly quiz question. Share your answer in live chat.\n\n{question}",
                "categoryId": "27",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
            "contentDetails": {
                "enableAutoStart": True,
                "enableAutoStop": True,
                "enableDvr": True,
                "enableEmbed": True,
                "latencyPreference": "low",
                "monitorStream": {"enableMonitorStream": False},
                "recordFromStart": True,
            },
        },
    ).execute()
    broadcast_id = response.get("id")
    if not broadcast_id:
        raise RuntimeError("YouTube did not return a broadcast ID")

    try:
        youtube.liveBroadcasts().bind(
            id=broadcast_id,
            part="id,contentDetails",
            streamId=stream_id,
        ).execute()
    except Exception:
        try:
            youtube.liveBroadcasts().delete(id=broadcast_id).execute()
        except Exception:
            LOG.exception("Could not remove unbound broadcast %s", broadcast_id)
        raise

    LOG.info("Created public YouTube broadcast %s", broadcast_id)
    return broadcast_id


def get_broadcast_state(youtube, broadcast_id: str) -> str:
    response = youtube.liveBroadcasts().list(
        part="status",
        id=broadcast_id,
    ).execute()
    items = response.get("items", [])
    if not items:
        return "missing"
    return items[0].get("status", {}).get("lifeCycleStatus", "unknown")


def delete_broadcast(youtube, broadcast_id: str) -> None:
    try:
        youtube.liveBroadcasts().delete(id=broadcast_id).execute()
        LOG.info("Removed unpublished broadcast %s before retry", broadcast_id)
    except Exception:
        LOG.exception("Could not remove unpublished broadcast %s", broadcast_id)


def is_permanent_youtube_error(error: Exception) -> bool:
    status = getattr(getattr(error, "resp", None), "status", None)
    return status in {400, 401, 403}


def generate_question() -> str:
    client = genai.Client(api_key=required_env("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=(
            "Write one original, thoughtful, family-friendly question for a YouTube "
            "live stream. Keep it under 22 words. Return only the question, with no "
            "numbering, quotation marks, or explanation."
        ),
    )
    question = (response.text or "").strip().strip('"\' ')
    if not question:
        raise RuntimeError("Gemini returned an empty question")
    return question[:240]


def generate_question_image(question: str) -> Image.Image:
    client = genai.Client(api_key=required_env("GEMINI_API_KEY"))
    interaction = client.interactions.create(
        model=os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"),
        input=(
            "Create a high-quality, photorealistic vertical 9:16 portrait for a family-friendly "
            "YouTube live question. Show a cheerful adult woman, clearly around 25 years old, "
            "as a friendly host, positioned in the upper third. Make the scene visually fit "
            f"this question: {question}. Keep the lower half uncluttered and darker for a "
            "readable text overlay. No text, letters, logos, or numbers."
        ),
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": "9:16",
            "image_size": "2K",
        },
    )
    generated_image = interaction.output_image
    if generated_image is None or not generated_image.data:
        raise RuntimeError("Gemini returned no image")

    image_bytes = base64.b64decode(generated_image.data)
    with Image.open(io.BytesIO(image_bytes)) as image:
        return image.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def font(
    size: int,
    bold: bool = False,
    serif: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
            if serif
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/georgiab.ttf" if serif else "C:/Windows/Fonts/arialbd.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrap_by_width(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=face)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]


def render_question(question: str, background: Image.Image) -> None:
    image = background.convert("RGBA").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (5, 18, 25, 75))
    image.alpha_composite(shade)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 16), fill=(238, 176, 74, 255))

    left, top, right, bottom = 56, 590, 1024, 1630
    draw.rounded_rectangle((left, top, right, bottom), radius=34, fill=(8, 22, 31, 232), outline=(230, 190, 116, 255), width=3)
    draw.rounded_rectangle((left + 54, top + 54, left + 240, top + 64), radius=5, fill=(238, 176, 74, 255))

    label_font = font(32, bold=True)
    footer_font = font(25, bold=True)
    draw.text((left + 54, top + 96), "TODAY'S QUESTION", font=label_font, fill=(255, 205, 120))

    max_text_width = right - left - 108
    max_text_height = bottom - top - 330
    for size in (78, 70, 62, 54, 46, 40):
        question_font = font(size, bold=True, serif=True)
        lines = wrap_by_width(draw, question, question_font, max_text_width)
        line_height = size + 22
        if len(lines) * line_height <= max_text_height:
            break
    text_height = len(lines) * line_height
    y = top + 210 + max(0, (max_text_height - text_height) // 2)
    for line in lines:
        draw.text((left + 64, y), line, font=question_font, fill=(245, 248, 242))
        y += line_height

    draw.text((left + 54, bottom - 92), "DROP YOUR ANSWER IN THE CHAT", font=footer_font, fill=(220, 232, 225))
    temporary = IMAGE_PATH.with_name("question.png.tmp")
    image.convert("RGB").save(temporary, format="PNG")
    temporary.replace(IMAGE_PATH)


def ffmpeg_command(ingestion_url: str, stream_key: str) -> list[str]:
    stream_url = f"{ingestion_url.rstrip('/')}/{stream_key}"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-re",
        "-f",
        "image2",
        "-loop",
        "1",
        "-framerate",
        "1",
        "-i",
        str(IMAGE_PATH.resolve()),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        "fps=30,scale=1080:1920:flags=lanczos,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "stillimage",
        "-b:v",
        "4500k",
        "-maxrate",
        "4500k",
        "-bufsize",
        "9000k",
        "-g",
        "60",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-f",
        "flv",
        stream_url,
    ]


def start_ffmpeg(ingestion_url: str, stream_key: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        ffmpeg_command(ingestion_url, stream_key),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def log_ffmpeg() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            LOG.warning("ffmpeg: %s", line.rstrip().replace(stream_key, "[redacted]"))

    threading.Thread(target=log_ffmpeg, daemon=True).start()
    LOG.info("FFmpeg streaming process started")
    return process


def stop_ffmpeg(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_timed_stream(stream_key: str, duration_seconds: int) -> None:
    youtube = create_youtube_service()
    stream = find_stream_for_key(youtube, stream_key)

    retry_seconds = 10
    while not STOP.is_set():
        try:
            question = generate_question()
            background = generate_question_image(question)
            render_question(question, background)
            LOG.info("Vertical question image generated")
            break
        except Exception:
            LOG.exception("Gemini asset generation failed; retrying in %s seconds", retry_seconds)
            if STOP.wait(retry_seconds):
                return
            retry_seconds = min(retry_seconds * 2, 300)

    if STOP.is_set():
        return

    process: subprocess.Popen[str] | None = None
    process_started_at: float | None = None
    connected_since: float | None = None
    counted_at: float | None = None
    broadcast_id: str | None = None
    remaining_seconds = float(duration_seconds)
    published = False
    retry_seconds = 10
    try:
        while not STOP.is_set() and remaining_seconds > 0:
            now = time.monotonic()

            if broadcast_id is None:
                try:
                    broadcast_id = create_live_broadcast(youtube, stream["id"], question)
                    retry_seconds = 10
                except Exception as error:
                    if is_permanent_youtube_error(error):
                        raise RuntimeError(
                            "YouTube rejected broadcast creation; check API authorization and channel live-stream eligibility"
                        ) from error
                    LOG.exception("Could not create YouTube broadcast; retrying in %s seconds", retry_seconds)
                    if STOP.wait(retry_seconds):
                        break
                    retry_seconds = min(retry_seconds * 2, 300)
                    continue

            if process is None:
                try:
                    process = start_ffmpeg(stream["ingestion_url"], stream_key)
                    process_started_at = time.monotonic()
                except Exception:
                    LOG.exception("Could not start FFmpeg; retrying in %s seconds", retry_seconds)
                    if STOP.wait(retry_seconds):
                        break
                    retry_seconds = min(retry_seconds * 2, 300)
                    continue
            elif process.poll() is not None:
                LOG.error("FFmpeg exited; retrying in %s seconds", retry_seconds)
                if counted_at is not None:
                    remaining_seconds -= now - counted_at
                stop_ffmpeg(process)
                process = None
                process_started_at = None
                connected_since = None
                counted_at = None
                if STOP.wait(retry_seconds):
                    break
                retry_seconds = min(retry_seconds * 2, 300)
                continue

            now = time.monotonic()
            try:
                broadcast_state = get_broadcast_state(youtube, broadcast_id)
            except Exception as error:
                if is_permanent_youtube_error(error):
                    raise RuntimeError("YouTube rejected a broadcast status request; check the OAuth authorization") from error
                LOG.exception("Could not read YouTube broadcast status; retrying")
                if counted_at is not None:
                    remaining_seconds -= now - counted_at
                    counted_at = None
                connected_since = None
                STOP.wait(retry_seconds)
                retry_seconds = min(retry_seconds * 2, 300)
                continue

            if broadcast_state == "complete" or broadcast_state == "missing":
                if counted_at is not None:
                    remaining_seconds -= now - counted_at
                stop_ffmpeg(process)
                process = None
                process_started_at = None
                connected_since = None
                counted_at = None
                broadcast_id = None
                LOG.info("Broadcast ended before the hour completed; creating a fresh broadcast")
                continue

            if broadcast_state == "live":
                if connected_since is None:
                    connected_since = now
                if now - connected_since >= 30:
                    if not published:
                        LOG.info("YouTube reports the broadcast live and stable; starting the one-hour timer")
                        published = True
                    if counted_at is None:
                        counted_at = now
                        retry_seconds = 10
                    else:
                        remaining_seconds -= now - counted_at
                        counted_at = now
                elif counted_at is not None:
                    remaining_seconds -= now - counted_at
                    counted_at = None
            else:
                connected_since = None
                if counted_at is not None:
                    remaining_seconds -= now - counted_at
                    counted_at = None
                if process_started_at is not None and now - process_started_at >= 300:
                    LOG.error("Broadcast did not become live after 5 minutes; recreating it")
                    stop_ffmpeg(process)
                    process = None
                    process_started_at = None
                    delete_broadcast(youtube, broadcast_id)
                    broadcast_id = None
                    if STOP.wait(retry_seconds):
                        break
                    retry_seconds = min(retry_seconds * 2, 300)
                    continue

            if remaining_seconds <= 0:
                break
            wait_seconds = 5
            if counted_at is not None:
                wait_seconds = min(wait_seconds, max(0, remaining_seconds - (now - counted_at)))
            STOP.wait(wait_seconds)
    finally:
        stop_ffmpeg(process)
    LOG.info("Timed stream finished")


def main(duration_seconds: int = 3600) -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stream_key = required_env("YOUTUBE_STREAM_KEY")
    required_env("GEMINI_API_KEY")
    if duration_seconds <= 0:
        raise ValueError("Stream duration must be greater than zero")
    if subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0:
        raise RuntimeError("FFmpeg is not installed or could not be started")

    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())

    run_timed_stream(stream_key, duration_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=3600)
    arguments = parser.parse_args()
    main(arguments.duration_seconds)
