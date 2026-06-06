# Xiaomi Mimo API Contract

Load this reference before making or editing Xiaomi Mimo API calls for the YouTube Chinese dubbing workflow.

## Documentation Source

The user provided the official documentation URL:

```text
https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/
```

Also use:

- `https://platform.xiaomimimo.com/llms.txt`
- `https://platform.xiaomimimo.com/static/docs/quick-start/first-api-call.md`
- `https://platform.xiaomimimo.com/static/docs/quick-start/model.md`
- `https://platform.xiaomimimo.com/static/docs/quick-start/error-codes.md`
- `https://platform.xiaomimimo.com/static/docs/api/audio/Speech-Recognition.md`
- `https://platform.xiaomimimo.com/static/docs/usage-guide/Speech-Recognition.md`
- `https://platform.xiaomimimo.com/static/docs/usage-guide/speech-synthesis-v2.5.md`

Do not guess production endpoints when these docs cannot be reached.

## Required Configuration

Keep secrets out of skill files and job manifests.

Expected runtime values:

- `MIMO_TOKEN_PLAN_API_KEY`: Xiaomi Mimo token-plan API credential, usually stored in `.env`.
- `MIMO_API_KEY`: compatibility fallback for older setups.
- `MIMO_API_BASE_URL`: Optional; default to `https://token-plan-cn.xiaomimimo.com/v1`.

Before calling the API, verify:

- Authentication header format. Use `api-key: $MIMO_TOKEN_PLAN_API_KEY`; `Authorization: Bearer ...` remains a compatibility option when supported.
- File input field names and MIME type requirements.
- Base64 data URL size limits for ASR and voice clone samples.
- Rate limits and error response shape.

## Endpoint and Authentication

Use the OpenAI-compatible endpoint:

```text
POST https://token-plan-cn.xiaomimimo.com/v1/chat/completions
```

Headers:

```text
api-key: $MIMO_TOKEN_PLAN_API_KEY
Content-Type: application/json
```

or:

```text
Authorization: Bearer $MIMO_TOKEN_PLAN_API_KEY
Content-Type: application/json
```

For this skill, store the key in `.env` as `MIMO_TOKEN_PLAN_API_KEY`.

## Models and Limits

ASR:

- `mimo-v2.5-asr`
- Capability: speech recognition
- Context window: 8k; maximum output: 2k
- Rate limit: maximum 100 RPM, 10k TPM

TTS:

- `mimo-v2.5-tts`: built-in high-quality voices; supports singing; does not support voice design or voice clone
- `mimo-v2.5-tts-voicedesign`: text-described voice design; does not support built-in voices, singing, or voice clone
- `mimo-v2.5-tts-voiceclone`: sample-based voice clone; does not support built-in voices, singing, or voice design
- TTS context window: 8k; maximum output: 8k
- TTS rate limit: maximum 100 RPM, 10M TPM

## ASR Normalization

ASR request:

```json
{
  "model": "mimo-v2.5-asr",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "input_audio",
          "input_audio": {
            "data": "data:audio/wav;base64,$BASE64_AUDIO"
          }
        }
      ]
    }
  ],
  "asr_options": {
    "language": "en"
  }
}
```

ASR notes:

- Supported audio formats: `wav` and `mp3`.
- Supported MIME types: `audio/wav`, `audio/mpeg`, `audio/mp3`.
- The Base64 encoded string must not exceed 10 MB.
- `asr_options.language` can be `auto`, `zh`, or `en`; use `en` for typical English YouTube sources.
- The response is a chat completion. Read `choices[0].message.content` for transcript text and keep the whole response in `mimo/asr_raw.json`.

Map the Mimo ASR result into `mimo/asr_segments.json` after chunking or timing repair:

```json
[
  {
    "id": "0001",
    "start": 12.34,
    "end": 16.78,
    "text": "English transcript",
    "speaker": "speaker_1"
  }
]
```

Rules:

- Use seconds for `start` and `end`.
- Preserve speaker labels if Mimo returns diarization.
- Split or merge segments only to improve dubbing timing; keep stable IDs after translation begins.
- Keep the raw Mimo response in `mimo/asr_raw.json`.
- Because the current public ASR docs show transcript text rather than word timestamps, preserve timing from audio chunks or repair timings during script adaptation.

## Chinese Segment Format

Write the adapted Chinese script to `segments.zh.json`:

```json
[
  {
    "id": "0001",
    "start": 12.34,
    "end": 16.78,
    "text_en": "English transcript",
    "text_zh": "中文配音台词",
    "speaker": "speaker_1",
    "voice": "冰糖",
    "notes": "shorten if generated audio exceeds 4.44s"
  }
]
```

Rules:

- Keep `id`, `start`, and `end` aligned with ASR unless manually repairing timing.
- Keep `text_zh` concise enough for natural speech within the segment duration.
- Use `voice` for built-in voices and `voice_profile` metadata for voice design or clone. Do not invent persistent voice IDs.

## Voice Clone and Voice Design

Voice clone:

- Ask the user to confirm rights or consent before cloning any real person's voice from a YouTube video.
- Use a clean sample from the source audio, ideally with minimal music and overlap.
- Supported sample formats: `mp3` and `wav`.
- Pass the sample as `audio.voice: "data:{MIME_TYPE};base64,$BASE64_AUDIO"` on each `mimo-v2.5-tts-voiceclone` TTS request.
- The Base64 encoded sample must not exceed 10 MB.
- Save clone metadata, including the local sample path and consent note, to `mimo/voice.json`. Do not store Base64 sample data in `voice.json`.

Voice design:

- Use when consent for cloning is missing or when the user prefers a designed voice.
- Specify Chinese language, style, pace, age range, gender presentation, energy, and affect if the API supports those controls.
- Pass the voice description as the `user` message on each `mimo-v2.5-tts-voicedesign` request.
- Keep the target spoken text in the `assistant` message.
- `audio.optimize_text_preview` is optional and can be `true`.
- Save the design prompt to `mimo/voice.json`.

Example normalized `mimo/voice.json`:

```json
{
  "strategy": "voice_design",
  "model": "mimo-v2.5-tts-voicedesign",
  "language": "zh-CN",
  "voice_design_prompt": "温暖清晰的中文纪录片旁白，中速，沉稳可信。",
  "source": "xiaomi_mimo"
}
```

## TTS Output

Generate one WAV file per Chinese segment:

```text
tts/0001.wav
tts/0002.wav
tts/0003.wav
```

Keep the raw response or job metadata in `mimo/tts_jobs.json`.

Built-in voice request:

```json
{
  "model": "mimo-v2.5-tts",
  "messages": [
    {
      "role": "user",
      "content": "温暖清晰的中文纪录片旁白，中速，沉稳可信。"
    },
    {
      "role": "assistant",
      "content": "这里是要合成的中文台词。"
    }
  ],
  "audio": {
    "format": "wav",
    "voice": "冰糖"
  }
}
```

Voice design request:

```json
{
  "model": "mimo-v2.5-tts-voicedesign",
  "messages": [
    {
      "role": "user",
      "content": "温暖清晰的中文纪录片旁白，中速，沉稳可信。"
    },
    {
      "role": "assistant",
      "content": "这里是要合成的中文台词。"
    }
  ],
  "audio": {
    "format": "wav",
    "optimize_text_preview": true
  }
}
```

Voice clone request:

```json
{
  "model": "mimo-v2.5-tts-voiceclone",
  "messages": [
    {
      "role": "user",
      "content": "自然、清晰、中速。"
    },
    {
      "role": "assistant",
      "content": "这里是要合成的中文台词。"
    }
  ],
  "audio": {
    "format": "wav",
    "voice": "data:audio/wav;base64,$BASE64_AUDIO"
  }
}
```

TTS response:

- The response is a chat completion.
- Decode `choices[0].message.audio.data` from Base64 and write it as the segment WAV.

For each segment:

- Send `text_zh` as the assistant message.
- Send style or voice design guidance as the user message.
- Prefer WAV output for assembly.
- Compare audio duration with `end - start`.
- If generated speech is too long, shorten the Chinese script before using aggressive speed changes.

## Failure Handling

Retry with bounded exponential backoff when:

- The API returns `429`, `500`, `502`, `503`, or `504`.
- The HTTP client raises a transport-layer error such as SSL record-layer failure, timeout, dropped connection, or temporary URL error.

Do not retry indefinitely. Keep each Mimo request idempotent by writing the response only after a complete successful response is decoded. For long videos, rerun the same resumable job command after a failure rather than deleting completed chunk outputs.

Stop and ask for user input when:

- Mimo credentials are missing.
- The user requests voice cloning but has not confirmed rights or consent.
- Mimo rejects an upload because of duration, size, format, quota, or policy.
- Generated audio is too misaligned to repair with minor text or speed changes.
