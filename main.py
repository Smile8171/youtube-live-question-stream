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
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def ffmpeg_command(stream_key: str) -> list[str]:
    stream_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
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


def start_ffmpeg(stream_key: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        ffmpeg_command(stream_key),
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


def configured_timezone() -> ZoneInfo:
    name = os.getenv("STREAM_TIMEZONE", "Asia/Kolkata").strip()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown stream timezone: {name}") from exc


def stream_window_active(now: datetime) -> bool:
    local_time = now.timetz().replace(tzinfo=None)
    return local_time >= day_time(19, 0) or local_time < day_time(2, 0)


def next_stream_start(now: datetime) -> datetime:
    start = datetime.combine(now.date(), day_time(19, 0), tzinfo=now.tzinfo)
    if now >= start:
        start += timedelta(days=1)
    return start


def stream_window_end(now: datetime) -> datetime:
    end_date = now.date() + timedelta(days=1 if now.hour >= 19 else 0)
    return datetime.combine(end_date, day_time(2, 0), tzinfo=now.tzinfo)


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
    attempt_started: float | None = None
    deadline: float | None = None
    paused_at: float | None = None
    retry_seconds = 10
    try:
        while not STOP.is_set():
            now = time.monotonic()
            if deadline is not None and paused_at is None and now >= deadline:
                break

            if process is None:
                try:
                    process = start_ffmpeg(stream_key)
                    attempt_started = time.monotonic()
                except Exception:
                    LOG.exception("Could not start FFmpeg; retrying in %s seconds", retry_seconds)
                    if STOP.wait(retry_seconds):
                        break
                    retry_seconds = min(retry_seconds * 2, 300)
                    continue
            elif process.poll() is not None:
                LOG.error("FFmpeg exited; retrying in %s seconds", retry_seconds)
                process = None
                attempt_started = None
                if deadline is not None and paused_at is None:
                    paused_at = now
                if STOP.wait(retry_seconds):
                    break
                retry_seconds = min(retry_seconds * 2, 300)
                continue

            now = time.monotonic()
            if deadline is None and attempt_started is not None and now - attempt_started >= 30:
                deadline = now + duration_seconds
                retry_seconds = 10
                LOG.info("FFmpeg stayed connected; starting the %s-second live timer", duration_seconds)
            elif deadline is not None and paused_at is not None and attempt_started is not None and now - attempt_started >= 30:
                deadline += now - paused_at
                paused_at = None
                retry_seconds = 10
                LOG.info("FFmpeg reconnected; resuming the live timer")

            wait_seconds = 1
            if deadline is not None and paused_at is None:
                wait_seconds = min(wait_seconds, max(0, deadline - now))
            STOP.wait(wait_seconds)
    finally:
        stop_ffmpeg(process)
    LOG.info("Timed stream finished")


def main(duration_seconds: int | None = None) -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stream_key = required_env("YOUTUBE_STREAM_KEY")
    required_env("GEMINI_API_KEY")
    stream_timezone = configured_timezone()
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("Stream duration must be greater than zero")
    if subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0:
        raise RuntimeError("FFmpeg is not installed or could not be started")

    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())

    if duration_seconds is not None:
        run_timed_stream(stream_key, duration_seconds)
        return

    process: subprocess.Popen[str] | None = None
    retry_seconds = 10

    try:
        while not STOP.is_set():
            now = datetime.now(stream_timezone)
            if not stream_window_active(now):
                if process is not None:
                    stop_ffmpeg(process)
                    process = None
                    retry_seconds = 10
                    LOG.info("Daily stream window ended")
                next_start = next_stream_start(now)
                LOG.info("Waiting for next stream window at %s", next_start.isoformat())
                STOP.wait(max(1, (next_start - now).total_seconds()))
                continue

            seconds_remaining = max(1, (stream_window_end(now) - now).total_seconds())
            if process is None:
                try:
                    question = generate_question()
                    background = generate_question_image(question)
                    render_question(question, background)
                    LOG.info("Question image generated for today's stream")
                    if not stream_window_active(datetime.now(stream_timezone)):
                        LOG.info("Question generation finished after the stream window")
                        continue
                    process = start_ffmpeg(stream_key)
                    retry_seconds = 10
                except Exception:
                    LOG.exception("Could not start scheduled stream; retrying in 5 minutes")
                    STOP.wait(min(300, seconds_remaining))
                    continue
            elif process.poll() is not None:
                LOG.error("FFmpeg exited; retrying in %s seconds", retry_seconds)
                if STOP.wait(min(retry_seconds, seconds_remaining)):
                    break
                process = None
                retry_seconds = min(retry_seconds * 2, 300)
                continue

            STOP.wait(min(15, seconds_remaining))
    finally:
        stop_ffmpeg(process)
        LOG.info("Streaming worker stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int)
    arguments = parser.parse_args()
    main(arguments.duration_seconds)
