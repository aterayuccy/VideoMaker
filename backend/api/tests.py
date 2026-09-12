from io import BytesIO
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from .views import (
    build_subtitle_cues,
    download_file,
    find_ffmpeg_executable,
    format_srt_timestamp,
    render_video_segment,
    split_subtitle_pages,
    write_subtitle_file,
)


class SubtitleFormattingTests(TestCase):
    @staticmethod
    def fixed_width_measure(text):
        return len(text) * 10

    def test_wraps_english_without_losing_text(self):
        text = "Phrase two is, Could you give me a hand? Use it to ask for help."
        pages = split_subtitle_pages(text, 140, self.fixed_width_measure)

        self.assertGreater(len(pages), 1)
        self.assertNotIn("...", "".join(pages))
        self.assertEqual(" ".join(" ".join(pages).split()), text)
        self.assertTrue(
            all(
                self.fixed_width_measure(line) <= 140
                for page in pages
                for line in page.splitlines()
            )
        )

    def test_wraps_by_rendered_glyph_width(self):
        def variable_width_measure(text):
            return sum(18 if character == "W" else 4 for character in text)

        pages = split_subtitle_pages("iiii iiii WWW", 40, variable_width_measure)
        lines = [line for page in pages for line in page.splitlines()]
        self.assertEqual(lines, ["iiii iiii", "WW", "W"])

    def test_unspaced_text_uses_at_most_two_lines_per_page(self):
        text = "這是一段沒有空格而且需要自動換行的中文字幕"
        pages = split_subtitle_pages(text, 60, self.fixed_width_measure)

        self.assertEqual("".join(page.replace("\n", "") for page in pages), text)
        self.assertTrue(all(len(page.splitlines()) <= 2 for page in pages))

    def test_cues_cover_complete_clip_without_gaps(self):
        cues = build_subtitle_cues(
            "This sentence is long enough to need several subtitle pages.",
            clip_duration=8.0,
            max_line_width=120,
            measure_text=self.fixed_width_measure,
        )

        self.assertEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[-1]["start"] + cues[-1]["duration"], 8.0)
        self.assertTrue(all(cue["duration"] > 0 for cue in cues))

    def test_writes_valid_srt_timestamps_and_complete_text(self):
        with TemporaryDirectory() as temp_dir:
            subtitle_path = Path(temp_dir) / "subtitle.srt"
            write_subtitle_file("第一句，第二句。", 3.25, 80, subtitle_path)
            subtitle = subtitle_path.read_text(encoding="utf-8")

        self.assertIn("00:00:00,000 -->", subtitle)
        self.assertIn("00:00:03,250", subtitle)
        self.assertEqual(format_srt_timestamp(3661.007), "01:01:01,007")
        self.assertEqual(
            "".join(line for line in subtitle.splitlines() if not line.isdigit() and "-->" not in line),
            "第一句，第二句。",
        )


class DownloadFileTests(SimpleTestCase):
    @patch("api.views.urlopen")
    @patch("api.views.default_storage.open", return_value=BytesIO(b"uploaded material"))
    def test_same_origin_media_uses_storage(self, storage_open_mock, urlopen_mock):
        request = RequestFactory().get("/", HTTP_HOST="testserver")

        with TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "video.mp4"
            download_file("https://testserver/media/material/video.mp4", target_path, request=request)

            self.assertEqual(target_path.read_bytes(), b"uploaded material")
            storage_open_mock.assert_called_once_with("material/video.mp4", "rb")
            urlopen_mock.assert_not_called()

    @patch("api.views.time.sleep")
    @patch("api.views.urlopen", side_effect=[TimeoutError("slow"), BytesIO(b"video")])
    def test_download_retries_after_timeout(self, urlopen_mock, sleep_mock):
        with TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "video.mp4"
            download_file("https://example.com/video.mp4", target_path)

            self.assertEqual(target_path.read_bytes(), b"video")
            self.assertEqual(urlopen_mock.call_count, 2)
            sleep_mock.assert_called_once_with(1)


class FfmpegRenderingTests(SimpleTestCase):
    def test_renders_video_audio_and_subtitles_without_moviepy(self):
        ffmpeg = find_ffmpeg_executable()
        if not ffmpeg:
            self.skipTest("FFmpeg is unavailable")

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_path = temp_path / "source.mp4"
            audio_path = temp_path / "voice.wav"
            subtitle_path = temp_path / "subtitle.srt"
            output_path = temp_path / "result.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=320x180:r=24:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                check=True,
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=1",
                    str(audio_path),
                ],
                check=True,
            )
            subtitle_path.write_text(
                "1\n00:00:00,000 --> 00:00:00,800\n測試字幕\n",
                encoding="utf-8",
            )

            render_video_segment(
                video_path,
                audio_path,
                subtitle_path,
                output_path,
                (320, 180),
                0.8,
            )

            self.assertGreater(output_path.stat().st_size, 0)


class RemovedFeatureTests(TestCase):
    def test_talking_material_endpoint_is_removed(self):
        self.assertEqual(self.client.post("/api/builtin-materials/").status_code, 404)

    def test_compose_rejects_talking_material_payload(self):
        response = self.client.post(
            "/api/video/compose/",
            data=json.dumps({
                "voice": "zh-TW-HsiaoChenNeural",
                "video_format": "short",
                "segments": [{"text": "Hello", "materialType": "builtin"}],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
