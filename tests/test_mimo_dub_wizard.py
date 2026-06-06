from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "mimo_dub_wizard.py"


def load_wizard():
    spec = importlib.util.spec_from_file_location("mimo_dub_wizard", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WizardTests(unittest.TestCase):
    def test_clean_youtube_start_params_removes_t_and_start(self):
        wizard = load_wizard()

        cleaned = wizard.clean_youtube_start_params("https://youtube.com/watch?v=abc&t=3157s&start=12&list=no")

        self.assertEqual(cleaned, "https://youtube.com/watch?v=abc&list=no")

    def test_prepare_command_uses_clean_url_for_full_scope(self):
        wizard = load_wizard()
        config = wizard.WizardConfig(
            url="https://youtube.com/watch?v=abc&t=3157s",
            job_dir=Path("work/job"),
            scope="full",
        )

        command = wizard.build_prepare_command(config)

        self.assertEqual(command[:3], [sys.executable, str(SKILL_DIR / "scripts" / "youtube_dub_pipeline.py"), "prepare"])
        self.assertIn("https://youtube.com/watch?v=abc", command)
        self.assertNotIn("t=3157s", command)
        self.assertNotIn("--clip-duration", command)

    def test_two_speaker_command_contains_blocking_runner_options(self):
        wizard = load_wizard()
        config = wizard.WizardConfig(
            url="https://youtube.com/watch?v=abc",
            job_dir=Path("work/job"),
            mode="two-speaker",
            source_video=Path("work/job/source.mp4"),
            output=Path("work/job/output/two_speaker_dub.mp4"),
            host_voice_sample=Path("work/job/mimo/host_sample.wav"),
            guest_voice_sample=Path("work/job/mimo/guest_sample.wav"),
            chunk_duration=60.0,
        )

        command = wizard.build_dub_command(config)

        self.assertEqual(command[:2], [sys.executable, str(SKILL_DIR / "scripts" / "two_speaker_mimo_dub.py")])
        self.assertIn("--host-voice-sample", command)
        self.assertIn("--guest-voice-sample", command)
        self.assertIn("--max-turn-tail-silence", command)
        self.assertIn("--min-atempo-factor", command)
        self.assertIn("--tts-workers", command)
        self.assertEqual(command[command.index("--tts-workers") + 1], "3")

    def test_run_paths_are_inside_job_dir(self):
        wizard = load_wizard()
        config = wizard.WizardConfig(
            url="https://youtube.com/watch?v=abc",
            job_dir=Path("work/job"),
        )

        paths = wizard.run_paths(config)

        self.assertEqual(paths.log, Path("work/job/run.log"))
        self.assertEqual(paths.exit, Path("work/job/run.exit"))

    def test_classification_maps_interview_to_two_speaker(self):
        wizard = load_wizard()
        config = wizard.WizardConfig(
            url="https://youtube.com/watch?v=abc",
            job_dir=Path("work/job"),
            content_type="auto",
            mode="auto",
        )
        classification = wizard.VideoClassification(
            content_type="interview",
            recommended_mode="two-speaker",
            recommended_voice_strategy="voice-clone",
            confidence=0.86,
            reason="Title and subtitles show an interview with questions and answers.",
        )

        wizard.apply_classification(config, classification)

        self.assertEqual(config.content_type, "interview")
        self.assertEqual(config.mode, "two-speaker")
        self.assertIn("访谈", config.voice_prompt)

    def test_classification_maps_tutorial_to_single_voice(self):
        wizard = load_wizard()
        config = wizard.WizardConfig(
            url="https://youtube.com/watch?v=abc",
            job_dir=Path("work/job"),
            content_type="auto",
            mode="auto",
        )
        classification = wizard.VideoClassification(
            content_type="solo",
            recommended_mode="single",
            recommended_voice_strategy="voice-clone",
            confidence=0.91,
            reason="Title says tutorial and subtitle preview is one continuous explanation.",
        )

        wizard.apply_classification(config, classification)

        self.assertEqual(config.content_type, "solo")
        self.assertEqual(config.mode, "single")
        self.assertIn("讲解", config.voice_prompt)

    def test_metadata_summary_keeps_bounded_subtitle_preview(self):
        wizard = load_wizard()
        metadata = {
            "title": "A practical tutorial",
            "description": "Long description " * 100,
            "channel": "Example",
            "duration": 1234,
            "tags": ["python", "tutorial"],
            "categories": ["Education"],
        }

        summary = wizard.metadata_summary(metadata, "hello " * 500, max_subtitle_chars=80)

        self.assertEqual(summary["title"], "A practical tutorial")
        self.assertLessEqual(len(summary["subtitle_preview"]), 80)
        self.assertEqual(summary["tags"], ["python", "tutorial"])

    def test_parse_vtt_subtitle_cues_preserves_timing(self):
        wizard = load_wizard()
        text = """WEBVTT

00:10:24.000 --> 00:10:27.000
Hello <c>world</c>

00:10:28.500 --> 00:10:30.000
This is a tutorial
"""

        cues = wizard.parse_subtitle_cues(text)

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start, 624.0)
        self.assertEqual(cues[0].end, 627.0)
        self.assertEqual(cues[0].text, "Hello world")

    def test_write_asr_from_subtitle_cues_uses_clip_offset(self):
        wizard = load_wizard()
        cues = [
            wizard.SubtitleCue(start=624.0, end=627.0, text="Opening line"),
            wizard.SubtitleCue(start=685.0, end=688.0, text="Second chunk line"),
        ]
        chunks = [
            {"id": "0001", "start": 0.0, "end": 60.0, "duration": 60.0},
            {"id": "0002", "start": 60.0, "end": 120.0, "duration": 60.0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            written = wizard.write_asr_from_subtitle_cues(job_dir, chunks, cues, subtitle_offset=624.0)

            self.assertEqual(written, 2)
            self.assertEqual((job_dir / "asr" / "0001.txt").read_text(encoding="utf-8").strip(), "Opening line")
            self.assertEqual((job_dir / "asr" / "0002.txt").read_text(encoding="utf-8").strip(), "Second chunk line")

    def test_subtitle_offset_uses_url_t_for_test_scope(self):
        wizard = load_wizard()
        config = wizard.WizardConfig(
            url="https://youtube.com/watch?v=abc&t=624s",
            job_dir=Path("work/job"),
            scope="test",
        )

        self.assertEqual(wizard.subtitle_offset_seconds(config), 624.0)


if __name__ == "__main__":
    unittest.main()
