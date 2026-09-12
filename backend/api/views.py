import asyncio
import gc
import json
import logging
import math
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponse
from rest_framework import generics, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Note, SavedVideo
from .serializers import NoteSerializer, SavedVideoSerializer

logger = logging.getLogger(__name__)

VIDEO_FORMATS = {
    "short": {
        "size": (720, 1280),
        "subtitle_top": 1070,
        "subtitle_width": 640,
    },
    "long": {
        "size": (1280, 720),
        "subtitle_top": 570,
        "subtitle_width": 1120,
    },
}
TARGET_VIDEO_SIZE = VIDEO_FORMATS["long"]["size"]
SUBTITLE_FONT_PATH = Path(
    os.getenv(
        "SUBTITLE_FONT_PATH",
        r"C:\Windows\Fonts\msjh.ttc"
        if os.name == "nt"
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
)
SUBTITLE_MAX_LINES = 2
SUBTITLE_FONT_SIZE = 36
SUBTITLE_HORIZONTAL_MARGIN = 24
SUBTITLE_VERTICAL_MARGIN = 18
SUBTITLE_STROKE_WIDTH = 3
VIDEO_DOWNLOAD_TIMEOUT = int(os.getenv("VIDEO_DOWNLOAD_TIMEOUT", "180"))
VIDEO_DOWNLOAD_RETRIES = int(os.getenv("VIDEO_DOWNLOAD_RETRIES", "3"))
VIDEO_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
PIXABAY_RESULTS_PER_PAGE = 30
PIXABAY_RESPONSE_LIMIT = 4 * 1024 * 1024


def find_ffmpeg_executable():
    ffmpeg_executable = shutil.which("ffmpeg")

    if ffmpeg_executable:
        return ffmpeg_executable

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError:
        return None

    bundled_executable = get_ffmpeg_exe()
    return bundled_executable if Path(bundled_executable).exists() else None


def close_media_resources(resources):
    seen = set()

    for resource in reversed(resources):
        resource_id = id(resource)

        if resource_id in seen:
            continue

        seen.add(resource_id)
        close = getattr(resource, "close", None)

        if close:
            close()

    resources.clear()
    gc.collect()


def concatenate_rendered_video_segments(segment_paths, output_path):
    if not segment_paths:
        raise RuntimeError("沒有可串接的影片片段。")

    if len(segment_paths) == 1:
        shutil.copyfile(segment_paths[0], output_path)
        return output_path

    ffmpeg_executable = find_ffmpeg_executable()

    if not ffmpeg_executable:
        raise RuntimeError("伺服器暫時無法串接影片片段。")

    concat_list_path = output_path.with_suffix(".txt")
    concat_list_path.write_text(
        "".join(
            "file '"
            + os.path.relpath(
                Path(segment_path).resolve(),
                concat_list_path.parent.resolve(),
            ).replace("\\", "/")
            + "'\n"
            for segment_path in segment_paths
        ),
        encoding="utf-8",
    )
    command = [
        ffmpeg_executable,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("影片片段串接逾時，請稍後再試。") from error

    if (
        result.returncode != 0
        or not output_path.exists()
        or output_path.stat().st_size == 0
    ):
        logger.error("FFmpeg segment concatenation failed: %s", result.stderr[-2000:])
        raise RuntimeError("影片片段串接失敗，請稍後再試。")

    return output_path


def format_srt_timestamp(seconds):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def write_subtitle_file(text, duration, max_line_width, target_path):
    cues = build_subtitle_cues(text, duration, max_line_width)
    blocks = []

    for index, cue in enumerate(cues, start=1):
        start = cue["start"]
        end = start + cue["duration"]
        blocks.append(
            f"{index}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{cue['text']}"
        )

    target_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def render_video_segment(video_path, audio_path, subtitle_path, output_path, target_size, duration):
    ffmpeg_executable = find_ffmpeg_executable()

    if not ffmpeg_executable:
        raise RuntimeError("伺服器尚未安裝 FFmpeg。")

    width, height = target_size
    escaped_subtitle_path = (
        subtitle_path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    )
    subtitle_margin = 100 if height > width else 70
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=24,"
        f"subtitles='{escaped_subtitle_path}':"
        "force_style='FontName=Noto Sans CJK TC,FontSize=30,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV={subtitle_margin}'"
    )
    command = [
        ffmpeg_executable,
        "-y",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-t",
        f"{duration:.3f}",
        "-vf",
        video_filter,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)

    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        logger.error("FFmpeg segment render failed: %s", result.stderr[-4000:])
        raise RuntimeError("影片片段轉檔失敗，請更換素材後再試。")


def workspace_id(request):
    try:
        return uuid.UUID(request.headers.get("X-Workspace-ID", ""))
    except (ValueError, AttributeError):
        raise ValidationError({"detail": "A valid X-Workspace-ID is required."})


class NoteListCreate(generics.ListCreateAPIView):
    serializer_class = NoteSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        workspace = workspace_id(self.request)
        return Note.objects.filter(workspace_id=workspace)

    def perform_create(self, serializer):
        if serializer.is_valid():
            serializer.save(workspace_id=workspace_id(self.request))
        else:
            print(serializer.errors)


class NoteDelete(generics.DestroyAPIView):
    serializer_class = NoteSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        workspace = workspace_id(self.request)
        return Note.objects.filter(workspace_id=workspace)


class SavedVideoListCreate(generics.ListCreateAPIView):
    serializer_class = SavedVideoSerializer
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]

    def get_queryset(self):
        return SavedVideo.objects.filter(workspace_id=workspace_id(self.request)).order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def create(self, request, *args, **kwargs):
        video_file = request.FILES.get("video")
        video_format = request.data.get("video_format") or SavedVideo.VideoFormat.LONG

        if video_format not in VIDEO_FORMATS:
            return Response({"detail": "Invalid video format."}, status=status.HTTP_400_BAD_REQUEST)

        if not video_file:
            return Response({"detail": "請先選擇要儲存的影片。"}, status=status.HTTP_400_BAD_REQUEST)

        saved_video = SavedVideo.objects.create(
            workspace_id=workspace_id(request),
            title=request.data.get("title") or "合成影片",
            video=video_file,
            video_format=video_format,
        )
        serializer = self.get_serializer(saved_video)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SavedVideoDelete(generics.DestroyAPIView):
    serializer_class = SavedVideoSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return SavedVideo.objects.filter(workspace_id=workspace_id(self.request))


EDGE_TTS_VOICES = {
    "zh-TW-HsiaoChenNeural": "曉臻（台灣女聲）",
    "zh-TW-YunJheNeural": "雲哲（台灣男聲）",
    "zh-CN-XiaoxiaoNeural": "曉曉（中文女聲）",
    "zh-CN-YunxiNeural": "雲希（中文男聲）",
    "en-US-JennyNeural": "Jenny（英文女聲）",
    "en-US-GuyNeural": "Guy（英文男聲）",
}


def get_edge_tts():
    try:
        import edge_tts
    except ImportError:
        return None

    return edge_tts


async def synthesize_tts_audio(text, voice):
    edge_tts = get_edge_tts()

    if edge_tts is None:
        raise RuntimeError("後端尚未安裝 edge-tts，請先安裝 requirements.txt。")

    communicate = edge_tts.Communicate(text, voice)
    audio_chunks = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])

    return b"".join(audio_chunks)


def copy_local_media_file(url, target_path, request):
    parsed_url = urlparse(url)
    media_path = urlparse(settings.MEDIA_URL).path
    request_host = request.get_host()

    if parsed_url.netloc and parsed_url.netloc != request_host:
        return False

    if not parsed_url.path.startswith(media_path):
        return False

    storage_name = unquote(parsed_url.path[len(media_path):]).lstrip("/")

    if not storage_name:
        raise RuntimeError("Local media URL does not identify a file.")

    with default_storage.open(storage_name, "rb") as source:
        with target_path.open("wb") as target:
            shutil.copyfileobj(source, target, VIDEO_DOWNLOAD_CHUNK_SIZE)

    if target_path.stat().st_size == 0:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("Local media file is empty.")

    return True


def download_file(url, target_path, request=None):
    if request and copy_local_media_file(url, target_path, request):
        return

    request = Request(url, headers={"User-Agent": "videomaker/1.0"})
    last_error = None

    for attempt in range(VIDEO_DOWNLOAD_RETRIES):
        try:
            with urlopen(request, timeout=VIDEO_DOWNLOAD_TIMEOUT) as response:
                with target_path.open("wb") as target:
                    while chunk := response.read(VIDEO_DOWNLOAD_CHUNK_SIZE):
                        target.write(chunk)

            if target_path.stat().st_size == 0:
                raise RuntimeError("Downloaded video is empty.")

            return
        except HTTPError:
            target_path.unlink(missing_ok=True)
            raise
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            target_path.unlink(missing_ok=True)
            last_error = error

            if attempt + 1 < VIDEO_DOWNLOAD_RETRIES:
                time.sleep(attempt + 1)

    raise RuntimeError(
        f"Video download failed after {VIDEO_DOWNLOAD_RETRIES} attempts: {last_error}"
    ) from last_error


def fit_video_clip_to_canvas(video_clip, target_size=TARGET_VIDEO_SIZE):
    target_width, target_height = target_size
    source_width, source_height = video_clip.size
    scale = max(target_width / source_width, target_height / source_height)
    resized_width = round(source_width * scale)
    resized_height = round(source_height * scale)
    resized_clip = video_clip.resized(new_size=(resized_width, resized_height))
    cropped_clip = resized_clip.cropped(
        width=target_width,
        height=target_height,
        x_center=resized_width // 2,
        y_center=resized_height // 2,
    )

    return cropped_clip, [resized_clip]


@lru_cache(maxsize=4)
def get_subtitle_font(font_size=SUBTITLE_FONT_SIZE):
    from PIL import ImageFont

    if SUBTITLE_FONT_PATH.exists():
        return ImageFont.truetype(str(SUBTITLE_FONT_PATH), font_size)

    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def measure_subtitle_text(text, font_size=SUBTITLE_FONT_SIZE):
    font = get_subtitle_font(font_size)
    return font.getlength(text) + (SUBTITLE_STROKE_WIDTH * 2)


def split_subtitle_pages(text, max_line_width, measure_text=None):
    """Fill each rendered line by pixel width, then group lines into subtitle pages."""
    clean_text = " ".join(text.split())

    if not clean_text:
        return []

    if max_line_width <= 0:
        raise ValueError("max_line_width must be greater than zero")

    measure = measure_text or measure_subtitle_text
    lines = []
    current_line = ""

    for word in clean_text.split(" "):
        candidate = f"{current_line} {word}".strip()

        if measure(candidate) <= max_line_width:
            current_line = candidate
            continue

        if current_line:
            lines.append(current_line)
            current_line = ""

        if measure(word) <= max_line_width:
            current_line = word
            continue

        # Chinese text and unusually long words may not contain spaces. Split
        # those tokens only when their actual rendered width exceeds the box.
        token_line = ""

        for character in word:
            token_candidate = f"{token_line}{character}"

            if token_line and measure(token_candidate) > max_line_width:
                lines.append(token_line)
                token_line = character
            else:
                token_line = token_candidate

        current_line = token_line

    if current_line:
        lines.append(current_line)

    return [
        "\n".join(lines[index : index + SUBTITLE_MAX_LINES])
        for index in range(0, len(lines), SUBTITLE_MAX_LINES)
    ]


def build_subtitle_cues(text, clip_duration, max_line_width, measure_text=None):
    """Distribute complete subtitle pages across the spoken clip duration."""
    pages = split_subtitle_pages(text, max_line_width, measure_text)

    if not pages or clip_duration <= 0:
        return []

    weights = [max(1, len(page.replace("\n", "").replace(" ", ""))) for page in pages]
    total_weight = sum(weights)
    cues = []
    start = 0.0

    for index, (page, weight) in enumerate(zip(pages, weights)):
        end = (
            clip_duration
            if index == len(pages) - 1
            else start + (clip_duration * weight / total_weight)
        )
        cues.append({"text": page, "start": start, "duration": end - start})
        start = end

    return cues


def normalize_builtin_position(position):
    if not isinstance(position, dict):
        return 0.5, 0.66

    try:
        x = float(position.get("x", 0.5))
        y = float(position.get("y", 0.66))
    except (TypeError, ValueError):
        return 0.5, 0.66

    return min(0.88, max(0.12, x)), min(0.86, max(0.16, y))


def draw_builtin_scene(draw, width, height, scene_id):
    horizon = int(height * 0.58)
    palettes = {
        "classroom": ("#dbeafe", "#b7794a"),
        "bedroom": ("#fde68a", "#c08457"),
        "garden": ("#93c5fd", "#86efac"),
        "beach": ("#7dd3fc", "#fde68a"),
        "cafe": ("#f5e6d3", "#9a6b49"),
        "forest": ("#bfdbfe", "#4ade80"),
        "rooftop": ("#312e81", "#1e293b"),
        "studio": ("#e2e8f0", "#cbd5e1"),
    }
    sky, ground = palettes.get(scene_id, palettes["studio"])
    draw.rectangle((0, 0, width, horizon), fill=sky)
    draw.rectangle((0, horizon, width, height), fill=ground)

    if scene_id == "classroom":
        draw.rectangle((int(width * 0.2), int(height * 0.16), int(width * 0.8), int(height * 0.39)), fill="#334155")
        for column in range(3):
            for row in range(2):
                x = int(width * (0.14 + column * 0.26))
                y = int(height * (0.64 + row * 0.16))
                draw.rectangle((x, y, x + int(width * 0.17), y + int(height * 0.055)), fill="#8b5e3c")
    elif scene_id == "bedroom":
        draw.rectangle((int(width * 0.17), int(height * 0.6), int(width * 0.83), int(height * 0.83)), fill="#a78bfa")
        draw.rectangle((int(width * 0.18), int(height * 0.56), int(width * 0.4), int(height * 0.65)), fill="#f8fafc")
        draw.rectangle((int(width * 0.1), int(height * 0.18), int(width * 0.3), int(height * 0.44)), fill="#93c5fd")
    elif scene_id == "garden":
        draw.ellipse((int(width * 0.74), int(height * 0.1), int(width * 0.9), int(height * 0.26)), fill="#fef3c7")
        for index in range(6):
            x = int(width * (0.02 + index * 0.18))
            draw.ellipse((x, int(height * 0.43), x + int(width * 0.2), int(height * 0.65)), fill="#65a30d")
    elif scene_id == "beach":
        draw.rectangle((0, int(height * 0.42), width, int(height * 0.67)), fill="#38bdf8")
        for index in range(4):
            y = int(height * (0.48 + index * 0.045))
            draw.arc((0, y - 12, width, y + 12), 180, 360, fill="#e0f2fe", width=max(2, int(height * 0.006)))
    elif scene_id == "cafe":
        draw.rectangle((0, int(height * 0.54), width, int(height * 0.66)), fill="#7c2d12")
        for x in (0.12, 0.54):
            draw.rectangle((int(width * x), int(height * 0.16), int(width * (x + 0.34)), int(height * 0.44)), fill="#dbeafe")
    elif scene_id == "forest":
        for index in range(7):
            x = int(width * (0.03 + index * 0.15))
            draw.rectangle((x, int(height * 0.3), x + int(width * 0.045), int(height * 0.72)), fill="#7c4a2d")
            draw.ellipse((x - int(width * 0.09), int(height * 0.12), x + int(width * 0.13), int(height * 0.42)), fill="#166534")
    elif scene_id == "rooftop":
        draw.ellipse((int(width * 0.71), int(height * 0.13), int(width * 0.85), int(height * 0.27)), fill="#fef3c7")
        for index in range(8):
            x = int(width * index * 0.14)
            draw.rectangle((x, int(height * (0.42 + (index % 3) * 0.05)), x + int(width * 0.12), horizon), fill="#0f172a")
    elif scene_id == "studio":
        for index in range(5):
            draw.line(
                (int(width * (0.1 + index * 0.2)), 0, int(width * (0.3 + index * 0.15)), int(height * 0.72)),
                fill="#94a3b8",
                width=max(2, int(width * 0.004)),
            )


def draw_builtin_object(draw, width, height, object_id, position, time):
    x = int(position[0] * width)
    y = int(position[1] * height)
    size = int(min(width, height) * 0.17)
    wave = math.sin(time * 4)

    if object_id == "cat":
        draw.ellipse((x - size // 3, y - size // 3, x + size // 3, y + size // 3), fill="#f59e0b")
        draw.ellipse((x + size // 16, y - size // 2, x + size // 2, y - size // 16), fill="#fbbf24")
        tail_end_x = x - int(size * (0.62 + wave * 0.12))
        tail_end_y = y - int(size * (0.3 + wave * 0.38))
        draw.line((x - size // 4, y, tail_end_x, tail_end_y), fill="#f59e0b", width=max(5, size // 9))
        draw.ellipse((x + size // 8, y - int(size * 0.33), x + int(size * 0.18), y - int(size * 0.23)), fill="#111827")
    elif object_id == "tree":
        draw.rectangle((x - size // 10, y - size // 10, x + size // 10, y + int(size * 0.62)), fill="#92400e")
        for index in range(3):
            offset = int(wave * size * 0.04)
            leaf_x = x + int((index - 1) * size * 0.22) + offset
            leaf_y = y - int(size * (0.45 + (index % 2) * 0.14))
            draw.ellipse((leaf_x - size // 4, leaf_y - size // 4, leaf_x + size // 4, leaf_y + size // 4), fill="#22c55e")
    elif object_id == "balloon":
        draw.ellipse((x - int(size * 0.3), y - int(size * 0.52), x + int(size * 0.3), y + int(size * 0.08)), fill="#f43f5e")
        draw.arc((x - int(size * 0.15), y, x + int(size * 0.15), y + int(size * 0.7)), 0, 180, fill="#475569", width=max(2, size // 40))
    elif object_id == "fish":
        draw.ellipse((x - int(size * 0.36), y - int(size * 0.2), x + int(size * 0.36), y + int(size * 0.2)), fill="#38bdf8")
        tail = int(wave * size * 0.12)
        draw.polygon(((x - int(size * 0.35), y), (x - int(size * 0.65), y - int(size * 0.22) + tail), (x - int(size * 0.65), y + int(size * 0.22) - tail)), fill="#0284c7")
        draw.ellipse((x + int(size * 0.15), y - int(size * 0.08), x + int(size * 0.21), y - int(size * 0.02)), fill="#0f172a")
    elif object_id == "rocket":
        draw.ellipse((x - int(size * 0.2), y - int(size * 0.45), x + int(size * 0.2), y + int(size * 0.45)), fill="#e2e8f0")
        flame = int(size * (0.55 + (wave + 1) * 0.1))
        draw.polygon(((x, y + int(size * 0.42)), (x - int(size * 0.11), y + flame), (x + int(size * 0.11), y + flame)), fill="#f97316")
        draw.ellipse((x - int(size * 0.075), y - int(size * 0.2), x + int(size * 0.075), y - int(size * 0.05)), fill="#38bdf8")
    elif object_id == "lamp":
        glow = int(size * (0.3 + (wave + 1) * 0.08))
        draw.ellipse((x - glow, y - glow, x + glow, y + glow), fill="#fef3c7")
        draw.rectangle((x - size // 24, y, x + size // 24, y + int(size * 0.52)), fill="#64748b")
        draw.polygon(((x - int(size * 0.28), y), (x + int(size * 0.28), y), (x + int(size * 0.16), y - int(size * 0.36)), (x - int(size * 0.16), y - int(size * 0.36))), fill="#facc15")
    elif object_id == "cloud":
        for offset_x, offset_y, radius in ((-0.2, 0, 0.22), (0, -0.12, 0.28), (0.23, 0, 0.22)):
            draw.ellipse((x + int(size * (offset_x - radius)), y + int(size * (offset_y - radius)), x + int(size * (offset_x + radius)), y + int(size * (offset_y + radius))), fill="#f8fafc")
        for index in range(3):
            drop = int(((time * 0.55 + index * 0.25) % 1) * size * 0.55)
            drop_x = x + int((index - 1) * size * 0.16)
            draw.line((drop_x, y + int(size * 0.18) + drop, drop_x, y + int(size * 0.32) + drop), fill="#60a5fa", width=max(2, size // 30))
    else:
        draw.line((x, y + int(size * 0.5), x + int(wave * size * 0.08), y - int(size * 0.1)), fill="#16a34a", width=max(3, size // 18))
        for index in range(6):
            angle = math.tau * index / 6 + wave * 0.13
            petal_x = x + int(math.cos(angle) * size * 0.2)
            petal_y = y - int(size * 0.1) + int(math.sin(angle) * size * 0.2)
            draw.ellipse((petal_x - size // 9, petal_y - size // 9, petal_x + size // 9, petal_y + size // 9), fill="#f472b6")
        draw.ellipse((x - size // 10, y - int(size * 0.2), x + size // 10, y), fill="#facc15")


@api_view(["GET"])
@permission_classes([AllowAny])
def tts_voices(request):
    data = [{"id": voice_id, "name": name} for voice_id, name in EDGE_TTS_VOICES.items()]
    return Response(data)


@api_view(["POST"])
@permission_classes([AllowAny])
def text_to_speech(request):
    text = request.data.get("text", "").strip()
    voice = request.data.get("voice", "zh-TW-HsiaoChenNeural")

    if not text:
        return Response({"detail": "請輸入片段內容。"}, status=status.HTTP_400_BAD_REQUEST)

    if len(text) > 3000:
        return Response({"detail": "片段內容太長，請控制在 3000 字以內。"}, status=status.HTTP_400_BAD_REQUEST)

    if voice not in EDGE_TTS_VOICES:
        return Response({"detail": "不支援這個聲音。"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        audio = asyncio.run(synthesize_tts_audio(text, voice))
    except Exception as error:
        return Response({"detail": f"TTS 產生失敗：{error}"}, status=status.HTTP_502_BAD_GATEWAY)

    response = HttpResponse(audio, content_type="audio/mpeg")
    response["Content-Disposition"] = 'inline; filename="voice.mp3"'
    return response


def choose_video_file(video_files):
    for quality in ("medium", "small", "tiny", "large"):
        video = video_files.get(quality)

        if video and video.get("url"):
            return video

    return None


@api_view(["POST"])
@permission_classes([AllowAny])
def search_pixabay_video(request):
    keyword = request.data.get("keyword", "").strip()
    min_duration = float(request.data.get("min_duration") or 0)
    api_key = settings.PIXABAY_API_KEY
    exclude_ids = request.data.get("exclude_ids", [])

    if not isinstance(exclude_ids, list):
        exclude_ids = []

    excluded_ids = {str(video_id) for video_id in exclude_ids}

    if not keyword:
        return Response({"detail": "請輸入素材關鍵字。"}, status=status.HTTP_400_BAD_REQUEST)

    if min_duration <= 0:
        return Response({"detail": "請先生成音檔，才能依照音檔長度選擇素材。"}, status=status.HTTP_400_BAD_REQUEST)

    if not api_key:
        return Response({"detail": "後端尚未設定 Pixabay API Key。"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    params = urlencode(
        {
            "key": api_key,
            "q": keyword,
            "video_type": "film",
            "safesearch": "true",
            "order": "popular",
            "per_page": PIXABAY_RESULTS_PER_PAGE,
        }
    )
    pixabay_url = f"https://pixabay.com/api/videos/?{params}"

    try:
        pixabay_request = Request(pixabay_url, headers={"User-Agent": "videomaker/1.0"})

        with urlopen(pixabay_request, timeout=12) as response:
            response_body = response.read(PIXABAY_RESPONSE_LIMIT + 1)

        if len(response_body) > PIXABAY_RESPONSE_LIMIT:
            return Response(
                {"detail": "Pixabay 回傳的素材資料過大，請縮小搜尋範圍。"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        data = json.loads(response_body.decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8") or "Pixabay 搜尋失敗。"
        return Response({"detail": detail}, status=error.code)
    except (URLError, TimeoutError) as error:
        return Response({"detail": f"Pixabay 連線失敗：{error}"}, status=status.HTTP_502_BAD_GATEWAY)

    for hit in data.get("hits", []):
        duration = hit.get("duration") or 0

        if str(hit.get("id")) in excluded_ids:
            continue

        if duration <= min_duration:
            continue

        video_file = choose_video_file(hit.get("videos", {}))

        if not video_file:
            continue

        return Response(
            {
                "id": hit.get("id"),
                "pageURL": hit.get("pageURL"),
                "tags": hit.get("tags", ""),
                "duration": duration,
                "trimStart": 0,
                "trimEnd": min_duration,
                "trimDuration": min_duration,
                "videoUrl": video_file.get("url"),
                "thumbnail": video_file.get("thumbnail"),
                "width": video_file.get("width"),
                "height": video_file.get("height"),
                "size": video_file.get("size"),
            }
        )

    return Response(
        {"detail": "找不到長度大於音檔的 Pixabay 影片素材。"},
        status=status.HTTP_404_NOT_FOUND,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def compose_video(request):
    voice = request.data.get("voice", "zh-TW-HsiaoChenNeural")
    video_format = request.data.get("video_format", "long")
    segments = request.data.get("segments", [])
    video_settings = VIDEO_FORMATS.get(video_format)

    if voice not in EDGE_TTS_VOICES:
        return Response({"detail": "不支援這個聲音。"}, status=status.HTTP_400_BAD_REQUEST)

    if not video_settings:
        return Response({"detail": "Invalid video format."}, status=status.HTTP_400_BAD_REQUEST)

    if not segments:
        return Response({"detail": "請先準備至少一個片段。"}, status=status.HTTP_400_BAD_REQUEST)

    for index, segment in enumerate(segments, start=1):
        if not segment.get("text", "").strip():
            return Response({"detail": f"片段 {index} 缺少旁白內容。"}, status=status.HTTP_400_BAD_REQUEST)

        material_type = segment.get("materialType", "external")

        if material_type != "external":
            return Response({"detail": f"片段 {index} 的素材類型無效。"}, status=status.HTTP_400_BAD_REQUEST)

        if not segment.get("videoUrl"):
            return Response({"detail": f"片段 {index} 尚未選擇素材。"}, status=status.HTTP_400_BAD_REQUEST)

    temp_dir = tempfile.TemporaryDirectory()
    try:
        temp_path = Path(temp_dir.name)
        segment_output_paths = []

        for index, segment in enumerate(segments, start=1):
            text = segment.get("text", "").strip()
            clip_duration = float(segment.get("duration") or 0)

            if clip_duration <= 0 or clip_duration > 600:
                raise RuntimeError(f"片段 {index} 的音檔長度無效。")

            audio_path = temp_path / f"audio_{index}.mp3"
            video_path = temp_path / f"video_{index}_external"
            subtitle_path = temp_path / f"subtitle_{index}.srt"
            segment_output_path = temp_path / f"rendered_segment_{index}.mp4"

            audio_path.write_bytes(asyncio.run(synthesize_tts_audio(text, voice)))
            download_file(segment["videoUrl"], video_path, request=request)
            write_subtitle_file(
                text,
                clip_duration,
                video_settings["subtitle_width"],
                subtitle_path,
            )
            render_video_segment(
                video_path,
                audio_path,
                subtitle_path,
                segment_output_path,
                video_settings["size"],
                clip_duration,
            )
            segment_output_paths.append(segment_output_path)

        output_path = temp_path / f"result_{uuid.uuid4().hex}.mp4"
        concatenate_rendered_video_segments(segment_output_paths, output_path)
    except Exception as error:
        temp_dir.cleanup()
        return Response(
            {"detail": f"影片合成失敗：{error}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    response = FileResponse(output_path.open("rb"), content_type="video/mp4")
    response._resource_closers.append(temp_dir.cleanup)
    response["Content-Disposition"] = 'inline; filename="composed-video.mp4"'
    response["Content-Length"] = str(output_path.stat().st_size)
    return response
