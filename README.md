# Mimo YouTube Chinese Dub

Local CLI and Web app for dubbing YouTube videos into Chinese with Xiaomi Mimo ASR, LLM translation, TTS voice clone, and voice design.

The project is intentionally local-first. API keys stay in `.env` or in the Web app's temporary key input; generated media and job caches are ignored by Git.

## What Is Included

- `scripts/mimo_dub_wizard.py` - interactive and non-interactive orchestration CLI.
- `scripts/full_mimo_dub.py` - resumable single-speaker full-video runner.
- `scripts/two_speaker_mimo_dub.py` - resumable two-speaker runner.
- `scripts/mimo_audio_api.py` - direct Mimo ASR/TTS helper.
- `scripts/youtube_dub_pipeline.py` - YouTube download, media prep, and assembly helpers.
- `webapp/` - local control panel at `http://127.0.0.1:8787`.
- `references/mimo-api-contract.md` and `docs/xiaomi-mimo/` - field notes and official doc snapshots.
- `SKILL.md` - Codex/agent skill instructions for this workflow.

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe`
- `yt-dlp`
- Xiaomi Mimo API access

On macOS:

```bash
brew install ffmpeg yt-dlp
```

## Configure

Create a local `.env` from the example:

```bash
cp .env.example .env
```

For Token Plan:

```bash
MIMO_TOKEN_PLAN_API_KEY=...
MIMO_API_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
```

For pay-as-you-go:

```bash
MIMO_API_KEY=...
MIMO_API_BASE_URL=https://api.xiaomimimo.com/v1
```

## Run The Web App

```bash
python3 webapp/app.py --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

The Web app can use `.env`, or you can choose temporary key input in the UI. Temporary keys are passed only through the child process environment.
Advanced settings include TTS concurrency. The default is 3 parallel Mimo TTS workers, which is usually faster than serial synthesis without being too aggressive on API rate limits.

## Run The CLI

Dry-run a job plan:

```bash
python3 scripts/mimo_dub_wizard.py \
  --url "https://www.youtube.com/watch?v=1VqKUrxR2C8&t=3157s" \
  --job-dir work/mimo-dub-test \
  --scope test \
  --content-type auto \
  --mode auto \
  --dry-run
```

Interactive mode:

```bash
python3 scripts/mimo_dub_wizard.py
```

## Notes

- YouTube subtitles are used before Mimo ASR when timed captions are available.
- The classifier uses title, description, metadata, and subtitle preview to choose single-speaker vs two-speaker mode.
- Long single-speaker TTS text is split into shorter Mimo TTS calls before concatenation to avoid whole-chunk voice clone failures.
- TTS synthesis runs concurrently by default with 3 workers. Use `--tts-workers N` in the CLI or `TTS 并发` in the Web app to tune it.
- Chinese sidecar subtitles are generated from `segments.zh.json` as `output/chinese_subtitles.srt` and `output/chinese_subtitles.vtt`.

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover -s webapp/tests -p 'test_*.py'
python3 -m py_compile scripts/*.py webapp/app.py
```
