---
name: mimo-youtube-chinese-dub
description: Use when a user provides a YouTube URL and wants an English or other-language video dubbed into Chinese with Xiaomi Mimo ASR, translation, TTS, voice clone, or voice design.
---

# YouTube Mimo Chinese Dub

## Overview

Produce a Chinese dubbed version of a YouTube video by preparing media locally, calling Xiaomi Mimo for speech services, translating and timing the script, synthesizing Chinese speech, and muxing the new audio back into the source video.

## Non-Negotiables

- Use Xiaomi Mimo API for ASR, TTS, voice clone, and voice design. If API credentials or access are missing, stop at a clear checkpoint and ask the user for the missing Mimo information.
- Do not use Whisper, Edge TTS, browser automation, or any other ASR/TTS provider as a hidden fallback.
- Before cloning a real person's voice from YouTube audio, ask the user to confirm they have rights or consent to clone that voice. If not confirmed, use Mimo voice design or a neutral Mimo voice instead.
- Keep source files, transcripts, translations, generated audio, and final video in a job directory. Do not overwrite the source video.
- For long videos, process a short clip first before running the full job.
- For long or full-video jobs, run the script in blocking foreground mode with stdout/stderr redirected to a job log. Wait for the command to exit, then inspect logs and verify outputs. Do not rapidly poll or stream chunk logs into the conversation.
- Make long jobs resumable: write chunk ASR, translation/turn JSON, TTS WAV, fitted WAV, and final manifests incrementally; rerunning the same command should skip valid existing files.
- Prefer existing YouTube subtitles or automatic captions over Mimo ASR when they have usable timestamps. Convert timed subtitles into `asr/0001.txt`, `asr/0002.txt`, etc.; only call Mimo ASR for chunks without subtitle text.
- Preserve speaker identity. If the source has multiple speakers, split turns and use a separate voice clone sample or voice strategy per speaker.
- Use a job-specific glossary for product names and terms. For the canonical test video, normalize `OpenCode`, `Open Code`, `open code`, and `开放代码` to `opencode`.

## Workflow

0. Prefer the interactive CLI for normal use.
   - Use `scripts/mimo_dub_wizard.py` when the user wants to run the flow outside the agent. It asks for URL, job directory, test/full scope, optional overrides, voice samples, and output path, then runs the long job in blocking mode and verifies the video.
   - If the user wants a local UI instead of running inside the agent, launch the repository Web app at `webapp/app.py`. It wraps the wizard, reads `.env`, analyzes YouTube metadata/subtitles, starts jobs, shows status/log tails, and previews the output video.

     ```bash
     /opt/homebrew/bin/python3 webapp/app.py --host 127.0.0.1 --port 8787
     ```

   - By default the wizard does not assume every video is an interview. It fetches YouTube title, description, tags, and available subtitle previews with `yt-dlp`, asks Mimo LLM to classify the video type, then chooses `single` or `two-speaker`.
   - Supported content types are `solo`, `interview`, `narration`, `multi-speaker`, `music`, and `unknown`. Only clear interview/podcast/Q&A videos should default to `two-speaker`; tutorials, lectures, narration, product videos, vlogs, game commentary, and uncertain multi-speaker videos should default to `single`.

     ```bash
     python scripts/mimo_dub_wizard.py
     ```

   - For non-interactive test planning without network or API calls:

     ```bash
     python scripts/mimo_dub_wizard.py \
       --url "https://www.youtube.com/watch?v=1VqKUrxR2C8&t=3157s" \
       --job-dir work/mimo-dub-test \
       --scope test \
       --content-type auto \
       --mode auto \
       --dry-run
     ```

   - Use the lower-level scripts directly only for debugging, custom automation, or when resuming an already-understood job.

1. Define the job.
   - Capture the YouTube URL, requested clip range or full-video scope, output directory, Chinese locale (`zh-CN` by default), and audio policy.
   - Default audio policy: replace the original audio with the Chinese dub. Only mix the original audio under the dub when the user asks for it.
   - If the URL contains `t=` or `start=`, treat it as a suggested test start time, not automatically as the whole processing range unless the user asks for a clip.
   - Classify the video before choosing the dubbing mode. Use title, description, tags, channel metadata, and subtitle preview when available. Do not default to interview mode only because a video has more than one possible voice.

2. Prepare local media.
   - Run a dry run first:

     ```bash
     python scripts/youtube_dub_pipeline.py prepare --url "<youtube-url>" --out-dir work/mimo-dub-job --dry-run
     ```

   - Then download and extract audio after network access and dependencies are available:

     ```bash
     python scripts/youtube_dub_pipeline.py prepare --url "<youtube-url>" --out-dir work/mimo-dub-job
     ```

   - The script expects `yt-dlp` and `ffmpeg` for real downloads. It creates a `job.json`, source video, mono 16 kHz WAV for ASR, `mimo/`, `tts/`, and `output/`.

3. Call Xiaomi Mimo ASR.
   - Before ASR, check for downloaded timed subtitles or automatic captions. If available, convert subtitle cues into chunk-level `asr/*.txt` files using the same chunk duration and clip offset as the prepared source video.
   - When `asr/<chunk-id>.txt` already exists, do not call Mimo ASR for that chunk. Treat the subtitle-derived file as the source transcript cache.
   - Read `references/mimo-api-contract.md` before implementing or editing Mimo API calls.
   - Use `mimo-v2.5-asr` through `https://token-plan-cn.xiaomimimo.com/v1/chat/completions`.
   - The official ASR input limit is a Base64 data URL of `wav` or `mp3` whose encoded string is no larger than 10 MB. Split long video audio into chunks before ASR.
   - For a single ASR test call:

     ```bash
     python scripts/mimo_audio_api.py asr --audio work/mimo-dub-job/source_16k_mono.wav --language en --output work/mimo-dub-job/mimo/asr.txt --raw-output work/mimo-dub-job/mimo/asr_raw.json
     ```

   - Normalize chunk-level or sentence-level results into `mimo/asr_segments.json`:

     ```json
     [
       {"id": "0001", "start": 12.34, "end": 16.78, "text": "English transcript"}
     ]
     ```

4. Translate and adapt into Chinese.
   - Translate segment by segment, preserving IDs and timing.
   - Prefer natural spoken Chinese over literal translation.
   - Shorten Chinese lines when needed to fit the original duration; mark any lines that still need timing repair.
   - Write `segments.zh.json`:

     ```json
     [
       {
         "id": "0001",
         "start": 12.34,
         "end": 16.78,
         "text_en": "English transcript",
         "text_zh": "中文配音台词"
       }
     ]
     ```

5. Select the Mimo voice strategy.
   - If using voice clone, collect a clean voice sample from the prepared source audio and confirm the user has rights or consent.
   - If there are multiple speakers, collect one clean sample per speaker and store them under `mimo/` with clear names such as `host_sample.wav` and `guest_sample.wav`.
   - Use two-speaker cloning only when classification or user input identifies a stable two-person interview or podcast. For general multi-speaker, panel, documentary, or uncertain videos, prefer `single` mode unless the user provides explicit speaker mapping.
   - If using voice design, write a Chinese voice description matching the target style, age, gender presentation, pace, and affect.
   - If using a built-in voice, choose one of `mimo_default`, `冰糖`, `茉莉`, `苏打`, or `白桦` for Chinese output unless the user asks otherwise.
   - Save selected voice metadata to `mimo/voice.json`. Mimo V2.5 TTS voice design and voice clone are direct TTS strategies, not persistent voice-ID creation flows.

6. Generate Mimo TTS.
   - Generate one WAV file per segment in `tts/`, named by segment ID such as `tts/0001.wav`.
   - Use `mimo-v2.5-tts` for built-in voices, `mimo-v2.5-tts-voicedesign` for text-described voices, and `mimo-v2.5-tts-voiceclone` for sample-cloned voices.
   - Put the target spoken Chinese text in the `assistant` message. Put style or voice design instructions in the `user` message.
   - For a single built-in voice test:

     ```bash
     python scripts/mimo_audio_api.py tts --strategy built-in --text "你好，这是中文配音测试。" --voice 冰糖 --output work/mimo-dub-job/tts/0001.wav
     ```

   - For a single voice design test:

     ```bash
     python scripts/mimo_audio_api.py tts --strategy voice-design --voice-design-prompt "温暖清晰的中文纪录片旁白，中速，沉稳可信。" --text "你好，这是中文配音测试。" --output work/mimo-dub-job/tts/0001.wav
     ```

   - For a single voice clone test:

     ```bash
     python scripts/mimo_audio_api.py tts --strategy voice-clone --voice-sample work/mimo-dub-job/mimo/voice_sample.wav --text "你好，这是中文配音测试。" --output work/mimo-dub-job/tts/0001.wav
     ```

   - Compare generated duration to `end - start`. If a segment is much too long, first shorten the Chinese line, then adjust TTS speed within natural limits.
   - If generated speech leaves too much trailing silence, first expand/restore concise Chinese content, then fit audio to the segment with a small tail-silence cap. Avoid padding every segment to the full original duration when the spoken line is much shorter.

7. Run long/full-video jobs in blocking mode.
   - For a single cloned or designed voice, use `scripts/full_mimo_dub.py` after preparing the source video.
   - For two-speaker interview-style videos, use `scripts/two_speaker_mimo_dub.py` with separate host and guest voice samples.
   - Redirect detailed logs to `run.log`, write `run.exit`, and wait for the process to exit before final verification:

     ```bash
     PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 python scripts/two_speaker_mimo_dub.py \
       --source-video work/mimo-dub-job/source.mp4 \
       --job-dir work/mimo-dub-job \
       --chunk-duration 60 \
       --output work/mimo-dub-job/output/two_speaker_dub.mp4 \
       --base-url https://token-plan-cn.xiaomimimo.com/v1 \
       --host-voice-sample work/mimo-dub-job/mimo/host_sample.wav \
       --guest-voice-sample work/mimo-dub-job/mimo/guest_sample.wav \
       --target-chars-per-second 10 \
       --pause-duration 0.2 \
       --max-turn-tail-silence 0.4 \
       --min-atempo-factor 0.55 \
       --tts-workers 3 \
       >> work/mimo-dub-job/run.log 2>&1
     code=$?
     echo "$code" > work/mimo-dub-job/run.exit
     exit "$code"
     ```

   - If the command fails, read the traceback, fix the root cause, and rerun the exact command. The long scripts are resumable and reuse existing chunk files.
   - If a user asks to reduce token/context use, keep the script running in blocking mode and avoid reading logs unless the process exits or the user asks for status.

8. Assemble the dubbed video.
   - Replace original audio:

     ```bash
     python scripts/youtube_dub_pipeline.py assemble --job-dir work/mimo-dub-job
     ```

   - Mix original audio quietly under the dub only when requested:

     ```bash
     python scripts/youtube_dub_pipeline.py assemble --job-dir work/mimo-dub-job --original-volume 0.12
     ```

9. Quality check.
   - Inspect the final video for missing segments, overlapping speech, long silence, bad pronunciation, mistranslations, and obvious timing drift.
   - Always run structural and decode checks before saying the full video is done:

     ```bash
     ffprobe -v error -show_entries format=duration,size \
       -show_entries stream=codec_type,codec_name,duration,width,height,sample_rate,channels \
       -of json work/mimo-dub-job/output/two_speaker_dub.mp4
     ffmpeg -v error -i work/mimo-dub-job/output/two_speaker_dub.mp4 -f null -
     ```

   - For jobs with a required glossary, scan source ASR and translated turn files for forbidden variants before final delivery.
   - For the user's test video, start with:

     ```bash
     python scripts/youtube_dub_pipeline.py prepare --url "https://www.youtube.com/watch?v=1VqKUrxR2C8&t=3157s" --out-dir work/mimo-dub-test --dry-run
     ```

## Mimo API Contract

Use `references/mimo-api-contract.md` whenever endpoint details, request schemas, response schemas, polling, file upload limits, authentication, or error handling need to be implemented or verified.

The official documentation entry point is `https://platform.xiaomimimo.com/llms.txt`; the relevant pages are the ASR guide, ASR API reference, TTS V2.5 guide, first API call guide, model limits, and error codes.

## Script Notes

- Use `scripts/mimo_dub_wizard.py` as the default human-facing CLI. It wraps preparation, voice sample extraction, long blocking runs, `run.log`/`run.exit`, and final ffprobe/ffmpeg checks.
- The wizard writes metadata and classification artifacts to `metadata/youtube.json`, `metadata/subtitle_preview.txt`, `metadata/classification_input.json`, and `metadata/classification.json`.
- When usable subtitles are available, the wizard writes `asr/*.txt` from subtitle cues and records `metadata/subtitle_asr_manifest.json`; this skips Mimo ASR for those chunks.
- The local Web app derives Chinese sidecar subtitles from `segments.zh.json` and writes `output/chinese_subtitles.srt` plus `output/chinese_subtitles.vtt`; the VTT file is attached to the browser video preview.
- `scripts/full_mimo_dub.py` automatically splits long single-speaker Chinese TTS text into shorter Mimo TTS calls before concatenation. This avoids whole-chunk voice clone failures where a 60-second generation can collapse into repeated filler sounds such as "咦".
- Single-speaker and two-speaker TTS synthesis use `--tts-workers`, defaulting to 3 concurrent Mimo TTS workers. Tune this down for rate limits or up cautiously for faster jobs. The Web app exposes the same setting as `TTS 并发`.
- Use `scripts/youtube_dub_pipeline.py check` to inspect local `yt-dlp`, `ffmpeg`, and `ffprobe` availability.
- Store token-plan credentials in `.env` as `MIMO_TOKEN_PLAN_API_KEY=...` and pay-as-you-go credentials as `MIMO_API_KEY=...`.
- The local Web app infers `.env` API type from the variable name. If the user enters a temporary key in the Web app, they must choose `Token Plan` or `按量 API`; temporary keys must not be written to job metadata, logs, or command-line arguments.
- Use `scripts/mimo_audio_api.py check` to inspect Mimo env vars and the configured base URL.
- Use `scripts/mimo_audio_api.py asr --dry-run ...` or `scripts/mimo_audio_api.py tts --dry-run ...` to inspect request payload shape without sending audio or requiring an API key.
- `scripts/mimo_audio_api.py` and the long-video helpers retry transient Mimo transport failures such as SSL record-layer failures, timeouts, 429, and 5xx responses with exponential backoff.
- `scripts/full_mimo_dub.py` is the field-tested resumable full-video runner for one voice strategy.
- `scripts/two_speaker_mimo_dub.py` is the field-tested resumable two-speaker runner; it semantically splits host and guest turns, so review representative chunks when speaker accuracy matters.
- Use `prepare --dry-run` before touching the network.
- Use `assemble` after Mimo TTS files exist.
- Keep any temporary adaptations local to the job directory unless the user asks to update this skill.
