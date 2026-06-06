from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class WebAppTests(unittest.TestCase):
    def test_build_wizard_command_uses_auto_defaults(self):
        payload = {
            "url": "https://www.youtube.com/watch?v=abc&t=624s",
            "job_dir": "/tmp/mimo-web-job",
            "scope": "test",
            "tts_workers": "3",
        }

        command = app.build_wizard_command(payload, dry_run=True)

        self.assertEqual(command[0], app.python_executable())
        self.assertIn(str(app.WIZARD_SCRIPT), command)
        self.assertIn("--content-type", command)
        self.assertIn("auto", command)
        self.assertIn("--mode", command)
        self.assertIn("--tts-workers", command)
        self.assertEqual(command[command.index("--tts-workers") + 1], "3")
        self.assertIn("--dry-run", command)

    def test_full_scope_omits_clip_options(self):
        command = app.build_wizard_command(
            {
                "url": "https://www.youtube.com/watch?v=abc&t=624s",
                "job_dir": "/tmp/mimo-web-job",
                "scope": "full",
                "clip_start": "624s",
                "clip_duration": "120s",
            },
            dry_run=True,
        )

        self.assertNotIn("--clip-start", command)
        self.assertNotIn("--clip-duration", command)

    def test_env_token_plan_key_selects_token_plan_profile(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("MIMO_TOKEN_PLAN_API_KEY=token-secret\n", encoding="utf-8")

            settings = app.resolve_api_settings({"env_file": str(env_file)}, require_key=True)

            self.assertEqual(settings.profile, app.TOKEN_PLAN_PROFILE)
            self.assertEqual(settings.key_env, "MIMO_TOKEN_PLAN_API_KEY")
            self.assertEqual(settings.base_url, "https://token-plan-cn.xiaomimimo.com/v1")

    def test_env_payg_key_selects_payg_profile(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("MIMO_API_KEY=payg-secret\n", encoding="utf-8")

            settings = app.resolve_api_settings({"env_file": str(env_file)}, require_key=True)

            self.assertEqual(settings.profile, app.PAYG_PROFILE)
            self.assertEqual(settings.key_env, "MIMO_API_KEY")
            self.assertEqual(settings.base_url, "https://api.xiaomimimo.com/v1")

    def test_manual_payg_key_sets_payg_base_url(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = app.resolve_api_settings(
                {
                    "api_key_source": "manual",
                    "api_profile": "payg",
                    "api_key": "manual-secret",
                },
                require_key=True,
            )

            self.assertEqual(settings.profile, app.PAYG_PROFILE)
            self.assertEqual(settings.key_env, "MIMO_API_KEY")
            self.assertEqual(settings.api_key, "manual-secret")
            self.assertEqual(settings.base_url, "https://api.xiaomimimo.com/v1")

    def test_create_job_record_persists_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = app.JobManager(Path(tmp))
            payload = {
                "url": "https://www.youtube.com/watch?v=abc",
                "job_dir": str(Path(tmp) / "job"),
                "scope": "test",
            }

            record = manager.create_record(payload, dry_run=True)

            self.assertTrue(record.job_id)
            self.assertEqual(record.status, "queued")
            saved = json.loads((record.job_dir / "webapp_job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["job_id"], record.job_id)
            self.assertEqual(saved["payload"]["url"], payload["url"])

    def test_create_job_record_does_not_persist_manual_api_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            manager = app.JobManager(Path(tmp) / "records")
            payload = {
                "url": "https://www.youtube.com/watch?v=abc",
                "job_dir": str(Path(tmp) / "job"),
                "scope": "test",
                "api_key_source": "manual",
                "api_profile": "payg",
                "api_key": "manual-secret",
            }

            record = manager.create_record(payload, dry_run=False)

            saved = json.loads((record.job_dir / "webapp_job.json").read_text(encoding="utf-8"))
            self.assertNotIn("api_key", saved["payload"])
            self.assertNotIn("manual-secret", json.dumps(saved))
            self.assertIn("https://api.xiaomimimo.com/v1", saved["command"])

    def test_custom_job_record_reloads_from_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "records"
            external_job = Path(tmp) / "outside" / "job"
            manager = app.JobManager(root)
            record = manager.create_record(
                {
                    "url": "https://www.youtube.com/watch?v=abc",
                    "job_dir": str(external_job),
                    "scope": "test",
                },
                dry_run=True,
            )
            fresh_manager = app.JobManager(root)

            loaded = fresh_manager._load_record(record.job_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.job_dir, external_job)

    def test_status_reads_run_exit_and_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = app.JobManager(Path(tmp))
            record = manager.create_record(
                {
                    "url": "https://www.youtube.com/watch?v=abc",
                    "job_dir": str(Path(tmp) / "job"),
                    "scope": "test",
                },
                dry_run=True,
            )
            (record.job_dir / "webapp.log").write_text("line1\nline2\n", encoding="utf-8")
            (record.job_dir / "run.exit").write_text("0\n", encoding="utf-8")

            status = manager.status(record.job_id)

            self.assertEqual(status["status"], "complete")
            self.assertEqual(status["exit_code"], 0)
            self.assertIn("line2", status["log_tail"])

    def test_generates_srt_and_vtt_from_single_speaker_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            job_dir.mkdir()
            (job_dir / "segments.zh.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "0001",
                            "start": 0,
                            "end": 10,
                            "duration": 10,
                            "text_zh": "第一句很短。第二句稍微长一点，用来确认字幕会被拆开。",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            paths = app.ensure_subtitles(job_dir)
            srt = paths["srt"].read_text(encoding="utf-8")
            vtt = paths["vtt"].read_text(encoding="utf-8")

            self.assertIn("1\n00:00:00,000 -->", srt)
            self.assertIn("第一句很短。", srt)
            self.assertTrue(vtt.startswith("WEBVTT\n\n"))
            self.assertIn("00:00:00.000 -->", vtt)

    def test_generates_subtitles_from_two_speaker_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            job_dir.mkdir()
            (job_dir / "segments.zh.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "0001",
                            "start": 5,
                            "end": 15,
                            "duration": 10,
                            "turns": [
                                {"speaker": "host", "text_zh": "欢迎回来。", "target_duration": 4},
                                {"speaker": "guest", "text_zh": "谢谢，我来讲一个例子。", "target_duration": 5},
                            ],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            srt = app.ensure_subtitles(job_dir)["srt"].read_text(encoding="utf-8")

            self.assertIn("00:00:05,000 -->", srt)
            self.assertIn("主持：欢迎回来。", srt)
            self.assertIn("嘉宾：谢谢，我来讲一个例子。", srt)

    def test_status_exposes_subtitle_urls_when_segments_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = app.JobManager(Path(tmp) / "records")
            record = manager.create_record(
                {
                    "url": "https://www.youtube.com/watch?v=abc",
                    "job_dir": str(Path(tmp) / "job"),
                    "scope": "test",
                },
                dry_run=True,
            )
            (record.job_dir / "segments.zh.json").write_text(
                json.dumps([{"id": "0001", "start": 0, "end": 2, "text_zh": "你好。"}], ensure_ascii=False),
                encoding="utf-8",
            )

            status = manager.status(record.job_id)

            self.assertEqual(status["subtitle_srt_url"], f"/api/jobs/{record.job_id}/subtitle.srt")
            self.assertEqual(status["subtitle_vtt_url"], f"/api/jobs/{record.job_id}/subtitle.vtt")

    def test_analyze_video_writes_classification_without_network_when_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "url": "https://www.youtube.com/watch?v=abc",
                "job_dir": str(Path(tmp) / "job"),
                "dry_run": True,
            }

            result = app.analyze_video(payload)

            self.assertEqual(result["classification"]["recommended_mode"], "single")
            self.assertTrue((Path(tmp) / "job" / "metadata" / "classification.json").exists())

    def test_requires_consent_for_auto_voice_non_dry_run(self):
        payload = {
            "url": "https://www.youtube.com/watch?v=abc",
            "mode": "auto",
            "voice_strategy": "auto",
        }

        self.assertTrue(app.requires_voice_consent(payload, dry_run=False))
        self.assertFalse(app.requires_voice_consent(payload, dry_run=True))

    def test_does_not_require_consent_for_single_voice_design(self):
        payload = {
            "url": "https://www.youtube.com/watch?v=abc",
            "mode": "single",
            "voice_strategy": "voice-design",
        }

        self.assertFalse(app.requires_voice_consent(payload, dry_run=False))


if __name__ == "__main__":
    unittest.main()
