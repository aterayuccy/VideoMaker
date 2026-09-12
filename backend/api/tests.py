import wave
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase
from PIL import Image
from rest_framework.test import APIClient

from .views import (
    BuiltinMaterialPreparationError,
    build_subtitle_cues,
    download_file,
    normalize_builtin_material_video,
    split_subtitle_pages,
)


class SubtitleFormattingTests(TestCase):
    @staticmethod
    def fixed_width_measure(text):
        return len(text) * 10

    def test_wraps_english_only_when_rendered_line_is_full(self):
        text = "Phrase two is, Could you give me a hand? Use it to ask for help."

        pages = split_subtitle_pages(
            text,
            max_line_width=140,
            measure_text=self.fixed_width_measure,
        )

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

    def test_wraps_by_glyph_width_instead_of_character_count(self):
        def variable_width_measure(text):
            return sum(18 if character == "W" else 4 for character in text)

        pages = split_subtitle_pages(
            "iiii iiii WWW",
            max_line_width=40,
            measure_text=variable_width_measure,
        )

        lines = [line for page in pages for line in page.splitlines()]
        self.assertEqual(lines[0], "iiii iiii")
        self.assertEqual(lines[1:], ["WW", "W"])

    def test_splits_unspaced_text_and_limits_pages_to_two_lines(self):
        pages = split_subtitle_pages(
            "這是一段沒有空格而且需要自動換行的中文字幕",
            60,
            self.fixed_width_measure,
        )

        self.assertEqual(
            "".join(page.replace("\n", "") for page in pages),
            "這是一段沒有空格而且需要自動換行的中文字幕",
        )
        self.assertTrue(all(len(page.splitlines()) <= 2 for page in pages))

    def test_cues_cover_the_complete_clip_without_gaps(self):
        cues = build_subtitle_cues(
            "This sentence is long enough to need several subtitle pages.",
            clip_duration=8.0,
            max_line_width=120,
            measure_text=self.fixed_width_measure,
        )

        self.assertEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(
            cues[-1]["start"] + cues[-1]["duration"],
            8.0,
        )
        self.assertTrue(all(cue["duration"] > 0 for cue in cues))
        self.assertTrue(
            all(
                current["start"] + current["duration"] == following["start"]
                for current, following in zip(cues, cues[1:])
            )
        )


class DownloadFileTests(SimpleTestCase):
    @patch("api.views.urlopen")
    @patch(
        "api.views.default_storage.open",
        return_value=BytesIO(b"uploaded built-in material"),
    )
    def test_same_origin_media_is_read_from_storage(
        self,
        storage_open_mock,
        urlopen_mock,
    ):
        request = RequestFactory().get("/", HTTP_HOST="testserver")

        with TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "video.webm"

            download_file(
                "https://testserver/media/builtin_materials/1/video.webm",
                target_path,
                request=request,
            )

            self.assertEqual(target_path.read_bytes(), b"uploaded built-in material")
            storage_open_mock.assert_called_once_with(
                "builtin_materials/1/video.webm",
                "rb",
            )
            urlopen_mock.assert_not_called()

    @patch("api.views.time.sleep")
    @patch(
        "api.views.urlopen",
        side_effect=[TimeoutError("slow response"), BytesIO(b"complete video")],
    )
    def test_download_retries_after_timeout(self, urlopen_mock, sleep_mock):
        with TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "video.mp4"

            download_file("https://example.com/video.mp4", target_path)

            self.assertEqual(target_path.read_bytes(), b"complete video")
            self.assertEqual(urlopen_mock.call_count, 2)
            sleep_mock.assert_called_once_with(1)


class BuiltinMaterialNormalizationTests(SimpleTestCase):
    @patch("api.views.subprocess.run")
    @patch("api.views.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_generates_timestamps_and_transcodes_mobile_webm(
        self,
        which_mock,
        run_mock,
    ):
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "mobile.webm"
            output_path = Path(temp_dir) / "normalized.mp4"
            source_path.write_bytes(b"webm")

            def create_output(command, **kwargs):
                output_path.write_bytes(b"mp4")
                return type("Result", (), {"returncode": 0})()

            run_mock.side_effect = create_output

            result = normalize_builtin_material_video(source_path, output_path)

            self.assertEqual(result, output_path)
            command = run_mock.call_args.args[0]
            self.assertIn("+genpts", command)
            self.assertIn("libx264", command)
            self.assertIn("yuv420p", command)
            self.assertEqual(command[-1], str(output_path))
            which_mock.assert_called_once_with("ffmpeg")

    @patch("api.views.subprocess.run")
    @patch("api.views.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_rejects_failed_mobile_webm_conversion(
        self,
        which_mock,
        run_mock,
    ):
        run_mock.return_value = type("Result", (), {"returncode": 1})()

        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "mobile.webm"
            output_path = Path(temp_dir) / "normalized.mp4"

            with self.assertRaises(BuiltinMaterialPreparationError):
                normalize_builtin_material_video(source_path, output_path)

        which_mock.assert_called_once_with("ffmpeg")


class BuiltinMaterialUploadTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="mobile-user",
            password="StrongPass123",
        )
        self.client.credentials(HTTP_X_WORKSPACE_ID="bcdebbad-1234-4234-8234-123456789abc")

    def test_accepts_fallback_image_when_mobile_video_is_unavailable(self):
        fallback_image = SimpleUploadedFile(
            "fallback.jpg",
            b"fallback image",
            content_type="image/jpeg",
        )

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                "/api/builtin-materials/",
                {"fallback_image": fallback_image},
                format="multipart",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["videoUrl"], "")
            self.assertTrue(response.data["fallbackImageUrl"].endswith(".jpg"))
            saved_files = list(Path(media_root).rglob("*.jpg"))
            self.assertEqual(len(saved_files), 1)

    def test_preserves_mp4_extension_for_supported_mobile_recording(self):
        video = SimpleUploadedFile(
            "recording.mp4",
            b"mobile mp4",
            content_type="video/mp4",
        )
        fallback_image = SimpleUploadedFile(
            "fallback.jpg",
            b"fallback image",
            content_type="image/jpeg",
        )

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                "/api/builtin-materials/",
                {"video": video, "fallback_image": fallback_image},
                format="multipart",
            )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data["videoUrl"].endswith(".mp4"))
            self.assertTrue(response.data["fallbackImageUrl"].endswith(".jpg"))

    @patch("api.views.synthesize_tts_audio", new_callable=AsyncMock)
    def test_composes_multiple_segments_with_fallback_images(
        self,
        synthesize_tts_audio_mock,
    ):
        audio_buffer = BytesIO()
        with wave.open(audio_buffer, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 4000)
        synthesize_tts_audio_mock.return_value = audio_buffer.getvalue()

        image_buffer = BytesIO()
        Image.new("RGB", (72, 128), "#38bdf8").save(image_buffer, format="JPEG")
        fallback_image = SimpleUploadedFile(
            "fallback.jpg",
            image_buffer.getvalue(),
            content_type="image/jpeg",
        )

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            upload_response = self.client.post(
                "/api/builtin-materials/",
                {"fallback_image": fallback_image},
                format="multipart",
            )
            compose_response = self.client.post(
                "/api/video/compose/",
                {
                    "voice": "zh-TW-HsiaoChenNeural",
                    "video_format": "short",
                    "segments": [
                        {
                            "text": f"Hello {index}",
                            "materialType": "builtin",
                            "videoUrl": "",
                            "fallbackImageUrl": upload_response.data["fallbackImageUrl"],
                            "loopMaterial": True,
                            "builtinScene": "classroom",
                        }
                        for index in range(1, 4)
                    ],
                },
                format="json",
            )

            self.assertEqual(compose_response.status_code, 200)
            self.assertEqual(compose_response["Content-Type"], "video/mp4")
            self.assertIn(b"ftyp", compose_response.content[:32])

    @patch(
        "api.views.normalize_builtin_material_video",
        side_effect=BuiltinMaterialPreparationError("unreadable mobile recording"),
    )
    @patch("api.views.synthesize_tts_audio", new_callable=AsyncMock)
    def test_composes_with_fallback_after_mobile_video_decode_failure(
        self,
        synthesize_tts_audio_mock,
        normalize_video_mock,
    ):
        audio_buffer = BytesIO()
        with wave.open(audio_buffer, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 4000)
        synthesize_tts_audio_mock.return_value = audio_buffer.getvalue()

        image_buffer = BytesIO()
        Image.new("RGB", (72, 128), "#f97316").save(image_buffer, format="JPEG")

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            upload_response = self.client.post(
                "/api/builtin-materials/",
                {
                    "video": SimpleUploadedFile(
                        "broken.webm",
                        b"broken mobile recording",
                        content_type="video/webm",
                    ),
                    "fallback_image": SimpleUploadedFile(
                        "fallback.jpg",
                        image_buffer.getvalue(),
                        content_type="image/jpeg",
                    ),
                },
                format="multipart",
            )
            compose_response = self.client.post(
                "/api/video/compose/",
                {
                    "voice": "zh-TW-HsiaoChenNeural",
                    "video_format": "short",
                    "segments": [
                        {
                            "text": "Hello",
                            "materialType": "builtin",
                            "videoUrl": upload_response.data["videoUrl"],
                            "fallbackImageUrl": upload_response.data["fallbackImageUrl"],
                            "loopMaterial": True,
                            "builtinScene": "classroom",
                        }
                    ],
                },
                format="json",
            )

            self.assertEqual(compose_response.status_code, 200)
            self.assertIn(b"ftyp", compose_response.content[:32])
            normalize_video_mock.assert_called_once()
