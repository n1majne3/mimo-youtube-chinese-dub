# Mimo Dub Web App

Local control panel for the Xiaomi Mimo YouTube Chinese dubbing workflow.

## Run

From the project root:

```bash
/opt/homebrew/bin/python3 webapp/app.py --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

The app reads the project `.env` by default:

```bash
MIMO_TOKEN_PLAN_API_KEY=...
```

It also supports the pay-as-you-go API:

```bash
MIMO_API_KEY=...
```

When `.env` is used, the app infers the API type from the variable name:

- `MIMO_TOKEN_PLAN_API_KEY` -> `https://token-plan-cn.xiaomimimo.com/v1`
- `MIMO_API_KEY` -> `https://api.xiaomimimo.com/v1`

If `.env` is missing, the UI automatically switches to temporary input. If `.env` is present, the UI uses it by default but still lets you choose `临时输入/覆盖`, select `Token Plan` or `按量 API`, and paste a one-off key. Temporary keys are passed only to the child process environment and are not written to job metadata or logs.

## Smoke Test

Use `Dry run` first. It should analyze and start a resumable wizard job without downloading video or calling Mimo.

For real runs, leave `Content type`, `Voice mode`, and `Voice strategy` on `auto` unless you want to override the classifier. If the source has usable YouTube subtitles, the wizard writes subtitle text into `asr/*.txt` and skips Mimo ASR for those chunks.

Generated job files live under `webapp/jobs/` by default, or in the custom job directory you enter. When `segments.zh.json` is available, the app writes Chinese sidecar subtitles to `output/chinese_subtitles.srt` and `output/chinese_subtitles.vtt`; the VTT track is attached to the video preview automatically.
