from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from .views import build_subtitle_cues, download_file, split_subtitle_pages


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
