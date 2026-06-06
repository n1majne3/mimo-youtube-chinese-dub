from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "full_mimo_dub.py"


def load_full_mimo():
    spec = importlib.util.spec_from_file_location("full_mimo_dub", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FullMimoDubTests(unittest.TestCase):
    def test_parser_defaults_to_three_tts_workers(self):
        module = load_full_mimo()

        args = module.build_parser().parse_args(["--source-video", "source.mp4", "--job-dir", "job"])

        self.assertEqual(args.tts_workers, 3)

    def test_build_job_adds_chunks_to_prepare_manifest(self):
        module = load_full_mimo()
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            source = job_dir / "source_clip.mp4"
            source.write_bytes(b"not a real video")
            manifest_path = job_dir / "job.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "created_by": "mimo-youtube-chinese-dub",
                        "paths": {"source_video": str(source)},
                    }
                ),
                encoding="utf-8",
            )
            module.ffprobe_duration = lambda _path: 120.0

            job = module.build_job(source, job_dir, 60.0)

            self.assertEqual(job["duration"], 120.0)
            self.assertEqual([chunk["id"] for chunk in job["chunks"]], ["0001", "0002"])
            self.assertEqual(job["paths"]["source_video"], str(source))
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual([chunk["id"] for chunk in saved["chunks"]], ["0001", "0002"])


if __name__ == "__main__":
    unittest.main()
