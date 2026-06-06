# Speech Recognition (MiMo-V2.5-ASR)

Speech recognition converts input audio into text output, suitable for meeting transcription, lyrics recognition, dialect transcription, noisy environment recordings, and more. You can improve recognition accuracy by specifying language parameters.

**Core Capabilities**

- **Broad Language and Dialect Coverage**: Supports bilingual Chinese-English recognition with automatic language detection. Natively recognizes Cantonese, Wu, Minnan, Sichuan, and other Chinese dialects.

- **Robust in Complex Scenarios**: Maintains stable recognition in noisy environments, far-field pickup, and multi-speaker overlapping conversations. Also supports lyrics transcription with background music.

- **Precise Handling of Specialized Content**: Accurately recognizes knowledge-intensive content such as classical poetry, technical terminology, proper nouns, and place names. Automatically generates punctuation without post-processing.

## Supported Models

Currently, only the `mimo-v2.5-asr` model is supported.

## Prerequisites

For API Key setup and other prerequisites, please refer to [First API Call](https://platform.xiaomimimo.com/#/docs/quick-start/first-api-call).

## Supported Audio Formats

Currently, only `wav` and `mp3` audio sample files are supported. Before passing audio to the API, convert the file to a Base64 encoded string. The encoded string size must not exceed 10 MB. 

The audio must be passed in data URL format: `data:{MIME_TYPE};base64,$BASE64_AUDIO`

**Supported formats and their MIME types:**

<table>
<colgroup>
<col style="width: 350px" />
<col style="width: 350px" />
</colgroup>
<thead>
<tr>
<th>Format</th>
<th>MIME Type</th>
</tr>
</thead>
<tbody>
<tr>
<td>wav</td>
<td>`audio/wav`</td>
</tr>
<tr>
<td>mp3</td>
<td>`audio/mpeg` or `audio/mp3`</td>
</tr>
</tbody>
</table>

## Code Sample

<div className='mdx-highlight'>

**Notes**
- Audio data must be passed via the `input_audio.data` field in data URL format.
- Use `asr_options.language` to specify the language. Auto-detection is applied if this parameter is not configured. Explicitly set the language when it is known to improve recognition accuracy. Supported values: `auto`, `zh`, `en`.

</div>

### Non-streaming Call

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-asr",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": "data:{MIME_TYPE};base64,$BASE64_AUDIO"
                    }
                }
            ]
        }
    ],
    "asr_options": {
        "language": "en"
    }
}'
```

**Python**

```python
import os
import base64
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

# Replace with the actual local file path
with open("audio_file.wav", "rb") as f:
    audio_bytes = f.read()
audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

completion = client.chat.completions.create(
    model="mimo-v2.5-asr",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": f"data:audio/wav;base64,{audio_base64}"
                    }
                }
            ]
        }
    ],
    extra_body={
        "asr_options": {
            "language": "en"
        }
    }
)

print(completion.model_dump_json())
```

### Streaming Call

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-asr",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": "data:{MIME_TYPE};base64,$BASE64_AUDIO"
                    }
                }
            ]
        }
    ],
    "asr_options": {
        "language": "auto"
    },
    "stream": true
}'
```

**Python**

```python
import os
import base64
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

# Replace with the actual local file path
with open("audio_file.wav", "rb") as f:
    audio_bytes = f.read()
audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

completion = client.chat.completions.create(
    model="mimo-v2.5-asr",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": f"data:audio/wav;base64,{audio_base64}"
                    }
                }
            ]
        }
    ],
    extra_body={
        "asr_options": {
            "language": "auto"
        }
    },
    stream=True
)

for chunk in completion:
    print(chunk.model_dump_json())
```

## Price

- Billing: Please refer to [Pay‑As‑You‑Go API](https://platform.xiaomimimo.com/#/docs/pricing).

- View Bill: You can view your usage on the [Billing](https://platform.xiaomimimo.com/#/console/usage) page in the Console.
