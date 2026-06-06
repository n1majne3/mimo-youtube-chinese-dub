# Context

## Glossary

### Xiaomi Mimo voice provider

The required provider for ASR, TTS, voice clone, and voice design in the YouTube Chinese redubbing workflow. The workflow must stop for user-provided Xiaomi Mimo access when credentials, API access, CLI access, or an authenticated browser session are missing; it must not silently substitute another ASR or TTS provider.

### Xiaomi Mimo API

The intended integration surface for the YouTube Chinese redubbing workflow. The skill should prefer API-based ASR, TTS, voice clone, and voice design calls over CLI or browser automation.

### Xiaomi Mimo official documentation

The user provided `https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/` as the API documentation source. The usable machine-readable index is `https://platform.xiaomimimo.com/llms.txt`, with relevant markdown pages for ASR, TTS V2.5, first API call, model limits, and error codes.

### Xiaomi Mimo chat completions audio API

The official documentation exposes ASR, TTS, voice design, and voice clone through the OpenAI-compatible `POST https://api.xiaomimimo.com/v1/chat/completions` endpoint. Authentication can use `api-key: $MIMO_API_KEY`; the skill should default `MIMO_API_BASE_URL` to `https://api.xiaomimimo.com/v1`.

### Xiaomi Mimo TTS voice strategy

Mimo V2.5 voice design and voice clone are direct TTS strategies rather than persistent voice-ID creation flows. Use `mimo-v2.5-tts` for built-in voices, `mimo-v2.5-tts-voicedesign` for text-described voices, and `mimo-v2.5-tts-voiceclone` for audio-sample cloning.
