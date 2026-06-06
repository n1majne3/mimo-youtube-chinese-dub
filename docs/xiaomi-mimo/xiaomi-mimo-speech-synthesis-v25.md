# Speech Synthesis (MiMo-V2.5-TTS Series)

Speech Synthesis (Text-to-Speech) supports automatically converting input text into natural and fluent speech output. You can generate natural and vivid speech content by configuring parameters such as speech style and voice.

**Core Capabilities**

- **Out-of-the-box built-in voices:** A variety of high-quality built-in voices are available for quick use without additional configuration.

- **Voice design and cloning:** Supports voice design via text description, or replication of arbitrary voices based on audio samples.

- **Diverse speech styles:** Supports control over speed, emotion, role-play, dialects and other styles, for more vivid and natural speech expression.

## List of Supported Models

Currently, three models of the MiMo-V2.5-TTS series are supported, and the model list is as follows:

<table>
<colgroup>
<col style="width: 243px" />
<col style="width: 228px" />
<col style="width: 240px" />
<col style="width: 307px" />
</colgroup>
<thead>
<tr>
<th>Model ID</th>
<th>Function</th>
<th>Voice</th>
<th>Precautions</th>
</tr>
</thead>
<tbody>
<tr>
<td>`mimo-v2.5-tts`</td>
<td>Use built-in high-quality voices for speech synthesis</td>
<td>Use the high-quality voices from the built-in voices list</td>
<td>Supports singing mode, does not support voice design and voice cloning</td>
</tr>
<tr>
<td>`mimo-v2.5-tts-voicedesign`</td>
<td>Customize voice through text description</td>
<td>Automatically generate voices from text descriptions, without requiring presets or audio samples</td>
<td>Does not support singing mode, built-in voices, or voice cloning</td>
</tr>
<tr>
<td>`mimo-v2.5-tts-voiceclone`</td>
<td>Replicate any voice from audio samples</td>
<td>Precisely replicate voices from audio samples to enable speech synthesis of any voice</td>
<td>Does not support singing mode, built-in voices, or voice design</td>
</tr>
</tbody>
</table>

## Preparation

For preparations such as obtaining API Key, please refer to [ First API Call ](https://platform.xiaomimimo.com/#/docs/quick-start/first-api-call). 

## General Precautions

<div className='mdx-highlight'>

**Call Rules**
- The target text for speech synthesis must be filled in the `role` of `assistant` message and cannot be placed in the `user` role message. 
- `user` role messages are optional parameters, and instructions can be passed in to adjust the tone and style of speech synthesis, or they can be conversation history (message content will not appear in synthesized speech). When using the `mimo-v2.5-tts-voicedesign` model, they are required parameters. 
- When using streaming calls, please specify the format of the output audio as `pcm16`, so that it can be spliced into a complete audio. For splicing examples, please refer to the Python calling methods in each chapter. 

</div>

## Style Control 

The instruction-following ability of the model is sufficient to cover the following complex controls (a single natural language instruction is sufficient to take effect): 

- **Multi-style Switching**: A single character completes the style transition from *announcement → whisper → roar* within the same voice segment, with a natural and unobtrusive transition.

- **Multi-emotion Mixing**: Supports complex emotions such as "repressed anger", "smile with a sob", "gentle but tired", "gentleness in mania", etc., rather than only allowing the selection of a single emotion.

- **Multi-granularity control**: From *paragraph level* (overall tone) → *sentence level* (rhythm) → *word level* (stress) → *character granularity* (choking, dragging, or breathy sound of a specific character), all can be specified in the instruction.

We currently offer two control methods: **natural language control** and **tag control** . The placement of the content for both methods in ` messages ` is different: 

- **Natural Language Control** → Placed in `role: user`'s `content`

- **Audio** **Tag Control**  → Placed in ` role: assistant ` 's ` content `

### Natural Language Control

Through natural language description, enable the model to understand and generate speech in the corresponding style. **The content is placed in the** `messages` **field of** `role: user` **in the** `content` **field.**   You can directly describe the desired speech style in a single sentence. 

**Example:**

> Report good news to the leader in a brisk and upbeat tone, speaking at a slightly faster pace, with the uncontrollable excitement and a touch of pride after learning the results, and a bright and energetic voice. 

> Looking at the results of the just-solved difficult problem, couldn't help exclaiming in a self-satisfied and overjoyed manner, with a high-pitched and bright voice, a relatively fast speaking speed, and a tone full of confidence and disbelief. 

> With a bright and lively teenage voice, carrying the pride and playfulness after a successful prank, speaking at a relatively fast pace with light enunciation, and the tone slightly rising when emphasizing the bet. 

On this basis, we also support a more complex and refined **director mode** — just like writing a script for actors, comprehensively depicting characters and voices from the three dimensions of **character, scene, and guidance**, based on which the model can generate more layered and performative voices.

- **[Character]** Clearly describe the character's identity, personality traits, physical appearance and speaking habits.

- **[Scene]** Describe what is happening at this moment, who you are talking to, and what emotional state you are in. The more specific the better — time, location, event, and the other person's reaction can all be included.

- **[Guidance]** Similar to a director giving acting instructions to an actor: speaking speed, breath control, pauses, accents, resonance position, timbre texture, and emotional fluctuations. It can be written in detail, and the model will act according to these "stage directions". 

**Example:**

```python
Role: The current head of the century-old noble Cen family. Since birth, she was adopted and raised by the gatekeeper of the ancestral temple, molded into a flawless, emotionless family totem. She has long lived in seclusion and has a strong sense of class alienation towards others.

Scene: In the shadows of the ancestral hall, she watches the man who has broken through the security cordon at all costs to find her and attempts to elope with her. She will use the coldest and most rigid class barriers to strangle both the other person and the feelings that have just sprouted but are enough to start a prairie fire within herself.

Guidance:
A cold, languid yet extremely imposing deep-voiced mature woman. Her vocal tract is very relaxed, without any sign of tension, yet exuding a bone-chilling sense of oppression.

- Speed and Pauses: Extremely slow, with each word rolling on the tip of her tongue before being uttered, carrying the casual arrogance of a superior. There are extremely long, unsettling pauses between sentences.
- Breathiness and Full Voice: Most of the time, her voice has no obvious pitch fluctuations, with a heavy and hard full voice, like a calm yet cold undercurrent. However, a very slight breathy sound must be added at certain final sounds (such as "sincerity") to reveal a hint of weariness and longing that even she herself is unaware of.
- Articulation Texture: The mixed use of literary and colloquial words bears the traces of the old era, with labiodental sounds pronounced extremely lightly but extremely clearly (such as "collision" and "cheap"), making her speech both elegant and sharp, hitting home with every word.
```

Director Mode is suitable for scenarios with high requirements for voice performance, such as character voiceovers, film-level content generation, etc.

### Audio Tag Control

By embedding style tags and audio tags in the text, fine-grained control over speech can be directly achieved. The overall style tag comes at the beginning, and fine-grained control tags can be inserted in the middle. **All tag control content is placed in the** ` messages ` **of the** ` role: assistant ` ` content `  **field.**  

Add a **start** `(style)` tag to the target text to specify the pronunciation style of the voice. Multiple styles can be set simultaneously by placing multiple style names within the same pair of parentheses, with no restrictions on the delimiter.

**Supported bracket formats:** Half-width `()`, full-width `（）`, or `[]` can be used.

**Format Example:** `(Style 1 Style 2)Content to be Synthesized`

The following are some recommended styles, and custom styles not listed are also supported. 

<div className='mdx-highlight'>

**Precautions** 
- To experience a better singing style, you must add the `(唱歌)` tag at the very beginning of the target text, with the format: `(唱歌)lyrics`. `Lyrics` are recommended to be in Chinese for better synthesis results. The identifiers within the tags support the following values, with equivalent effects: 

- `唱歌`, `sing`, `singing`

</div>

<table>
<colgroup>
<col style="width: 159px" />
<col style="width: 697px" />
</colgroup>
<thead>
<tr>
<th>**Style Type**</th>
<th>**Style Example**</th>
</tr>
</thead>
<tbody>
<tr>
<td>Basic Emotions</td>
<td>*Happy / Sad / Angry / Fearful / Amazed / Excited / Wronged / Calm / Indifferent*</td>
</tr>
<tr>
<td>Complex Emotions</td>
<td>*Melancholy / Relieved / Helpless / Guilty / Relieved / Jealous / Tired / Apprehensive / Emotional*</td>
</tr>
<tr>
<td>Overall tone</td>
<td>*Gentle / Cold / Lively / Serious / Lazy / Playful / Deep / Capable / Sharp*</td>
</tr>
<tr>
<td>Timbre Positioning</td>
<td>*Magnetic / Mellow / Clear / Ethereal / Innocent / Old / Sweet / Hoarse / Elegant*</td>
</tr>
<tr>
<td>Character Tone</td>
<td>*Clamp voice / Big Sister voice / Shota voice / Uncle voice / Taiwanese accent*</td>
</tr>
<tr>
<td>Dialect</td>
<td>*Northeast dialect / Sichuan dialect / Henan dialect / Cantonese*</td>
</tr>
<tr>
<td>Role-playing</td>
<td>*Sun Wukong / Lin Daiyu*</td>
</tr>
<tr>
<td>Singing</td>
<td>*singing*</td>
</tr>
</tbody>
</table>

**Example:**
- `(Sighing)After all these years, when I walked down that street again, a part of my heart suddenly felt empty.`
- `(Lazy)Let me sleep for five more minutes... just five minutes, really, for the last time.`
- `(Magnetic)The night is already deep, but the city is still breathing. I'm the one accompanying you tonight. Welcome to listen to <Midnight Radio>.`
- `(Northeastern dialect)Oh my goodness, it's so cold today! You know that wind, it's whistling like a knife, cutting into your face!`
- `(Cantonese)This is really amazing! Once you've tasted it, you won't forget!`
- `(singing)Forgive me for my unruly and unrestrained love for freedom throughout my life, and I'm also afraid that one day I'll fall, Oh no. Abandoning ideals, anyone can do it, so how could I be afraid that one day it'll only be you and me.`

On this basis, we also support inserting `[audio tag]` at any position in the text. Through the [audio tag], you can perform fine-grained control over the sound, precisely adjusting tone, mood, and expression style—whether it's a whisper, a hearty laugh, or a little complaint with a touch of emotion. You can also flexibly insert breathing sounds, pauses, coughs, etc., all of which can be easily achieved. The speaking speed can also be flexibly adjusted, allowing each sentence to have its proper rhythm.

<table>
<colgroup>
<col style="width: 218px" />
<col style="width: 697px" />
</colgroup>
<thead>
<tr>
<th>**Style Type**</th>
<th>**Style Example**</th>
</tr>
</thead>
<tbody>
<tr>
<td>Speech Rate and Rhythm</td>
<td>*Inhale / Take a deep breath / Sigh / Let out a long sigh / Pant / Hold one's breath*</td>
</tr>
<tr>
<td>Emotional State</td>
<td>*nervous / scared / excited / tired / wronged / coquettish / guilty / shocked / impatient*</td>
</tr>
<tr>
<td>Speech Features</td>
<td>*Trembling / Voice trembling / Pitch change / Cracked voice / Nasal voice / Breathiness / Hoarseness*</td>
</tr>
<tr>
<td>Laughing and crying tone</td>
<td>*Smile / Chuckle / Laugh out loud / Sneer / Sob / Whimper / Choke / Wail*</td>
</tr>
</tbody>
</table>

**Example:**
- (nervously, takes a deep breath) Hoo... Calm down, calm down. It's just an interview... (speaking faster, muttering) I've rehearsed my self-introduction fifty times, it should be okay. Come on, you can do it... (softly) Oh, is my tie crooked?
- (extremely exhausted, listless) Master... wake me up when we get there... (sighs deeply) I'll take a little nap first. This overtime has made me feel like my soul is about to scatter. 
- If I had... (pauses for a moment) even if I had persisted for just one more second, would the outcome have been different? (forced smile) Oh, there are no "what ifs" anymore. 
- (Rapid breathing due to the cold) Hoo—hoo—This, this snow in the Greater Khingan Mountains... (cough) It can literally freeze one's bones... Don't, don't stop, keep moving, move quickly. 
- (raising voice and shouting) Sister! This fish is fresh! Just caught this morning! Hey! You there, stop rummaging around! If you crush it, you'll have to pay for it! 

## Speech Synthesis Using Built-in Voices

- It comes with multiple high-quality voices and can be used directly without additional configuration. Currently, only the `mimo-v2.5-tts` model is supported

- Supports controlling the style of synthetic speech by passing natural language instructions in the user message

- Supports controlling the style of synthesized speech through audio tags 

### Built-in Voice List

When in use, you can set the preset timbre in `{"audio": {"voice": "mimo_default"}}`.

<table>
<colgroup>
<col style="width: 109px" />
<col style="width: 127px" />
<col style="width: 113px" />
<col style="width: 598px" />
</colgroup>
<thead>
<tr>
<th>**Voice** **Name**</th>
<th>**Voice ID**</th>
<th>Language</th>
<th>Gender</th>
</tr>
</thead>
<tbody>
<tr>
<td>MiMo-默认</td>
<td>mimo_default</td>
<td colspan="2">It varies depending on the deployed cluster. The default for the China cluster is `冰糖`, and the default for other clusters is `Mia`</td>
</tr>
<tr>
<td>冰糖</td>
<td>冰糖</td>
<td>Chinese</td>
<td>Female</td>
</tr>
<tr>
<td>茉莉</td>
<td>茉莉</td>
<td>Chinese</td>
<td>Female</td>
</tr>
<tr>
<td>苏打</td>
<td>苏打</td>
<td>Chinese</td>
<td>Male</td>
</tr>
<tr>
<td>白桦</td>
<td>白桦</td>
<td>Chinese</td>
<td>Male</td>
</tr>
<tr>
<td>Mia</td>
<td>Mia</td>
<td>English</td>
<td>Female</td>
</tr>
<tr>
<td>Chloe</td>
<td>Chloe</td>
<td>English</td>
<td>Female</td>
</tr>
<tr>
<td>Milo</td>
<td>Milo</td>
<td>English</td>
<td>Male</td>
</tr>
<tr>
<td>Dean</td>
<td>Dean</td>
<td>English</td>
<td>Male</td>
</tr>
</tbody>
</table>

### Code Sample

#### Non-streaming Call

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-tts",
    "messages": [
        {
            "role": "user",
            "content": "Bright, bouncy, slightly sing-song tone — like you are bursting with good news you can barely hold in. Fast pace, rising pitch at the end."
        },
        {
            "role": "assistant",
            "content": "Hey boss — guess what, guess what? I just got the results back and I actually passed! Not just passed, I got a distinction! I know, I know — you told me I was cutting it close, but hey, here we are. Drinks are on me tonight, okay?"
        }
    ],
    "audio": {
        "format": "wav",
        "voice": "Chloe"
    }
}'
```

**Python**

```python
import os
from openai import OpenAI
import base64

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

completion = client.chat.completions.create(
    model="mimo-v2.5-tts",
    messages=[
        {
            "role": "user",
            "content": "Bright, bouncy, slightly sing-song tone — like you're bursting with good news you can barely hold in. Fast pace, rising pitch at the end."
        },
        {
            "role": "assistant",
            "content": "Hey boss — guess what, guess what? I just got the results back and I actually passed! Not just passed, I got a distinction! I know, I know — you told me I was cutting it close, but hey, here we are. Drinks are on me tonight, okay?"
        }
    ],
    audio={
        "format": "wav",
        "voice": "Chloe"
    }
)

message = completion.choices[0].message
audio_bytes = base64.b64decode(message.audio.data)
with open("audio_file.wav", "wb") as f:
    f.write(audio_bytes)
```

#### Streaming Call

<div className='mdx-highlight'>

- The low-latency streaming output feature of the MiMo-V2.5-TTS series is not yet available. If you have relevant requirements, please follow the upcoming feature updates.
- The streaming call interface is currently downgraded to compatibility mode, and only **returns the results once in streaming format after all inferences are completed.** 

</div>

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-tts",
    "messages": [
        {
            "role": "user",
            "content": "Bright, bouncy, slightly sing-song tone — like you are bursting with good news you can barely hold in. Fast pace, rising pitch at the end."
        },
        {
            "role": "assistant",
            "content": "Hey boss — guess what, guess what? I just got the results back and I actually passed! Not just passed, I got a distinction! I know, I know — you told me I was cutting it close, but hey, here we are. Drinks are on me tonight, okay?"
        }
    ],
    "audio": {
        "format": "pcm16",
        "voice": "Chloe"
    },
    "stream": true
}'
```

**Python**

```python
import base64
import os
import numpy as np
import soundfile as sf
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

completion = client.chat.completions.create(
    model="mimo-v2.5-tts",
    messages=[
        {
            "role": "user",
            "content": "Bright, bouncy, slightly sing-song tone — like you're bursting with good news you can barely hold in. Fast pace, rising pitch at the end."
        },
        {
            "role": "assistant",
            "content": "Hey boss — guess what, guess what? I just got the results back and I actually passed! Not just passed, I got a distinction! I know, I know — you told me I was cutting it close, but hey, here we are. Drinks are on me tonight, okay?"
        }
    ],
    audio={
        "format": "pcm16",
        "voice": "Chloe"
    },
    stream=True
)

# 24kHz PCM16LE mono audio
collected_chunks: np.ndarray = np.array([], dtype=np.float32)

for chunk in completion:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    audio = getattr(delta, "audio", None)

    if audio is not None:
        assert isinstance(audio, dict), f"Expected audio to be a dict, got {type(audio)}"
        pcm_bytes = base64.b64decode(audio["data"])
        np_pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        collected_chunks = np.concatenate((collected_chunks, np_pcm))
        print(f"Received audio chunk of size {len(pcm_bytes)} bytes")

# Save the collected audio to a file
os.makedirs("tmp", exist_ok=True)
sf.write("tmp/output.wav", collected_chunks, samplerate=24000)
print("Audio saved to tmp/output.wav")
```

## Speech Synthesis Using Voice Design

There is no need to provide an audio file. Simply add voice description text to the message with the role of `user`, and a customized voice can be generated. Currently, only the `mimo-v2.5-tts-voicedesign` model is supported.

### How to Write a Good Voice Design Prompt

When using the `mimo-v2.5-tts-voicedesign` model, the text in the `user` message is the voice design description. The more specific and vivid the description, the closer the generated voice will be to the expected one.

#### Key Dimension

A good voice description usually covers the following multiple dimensions (not necessarily comprehensive):

<table>
<colgroup>
<col style="width: 200px" />
<col style="width: 594px" />
</colgroup>
<thead>
<tr>
<th>Dimension</th>
<th>Example</th>
</tr>
</thead>
<tbody>
<tr>
<td>Gender and Age</td>
<td>"young woman in her mid-20s", "middle-aged man in his 50s"</td>
</tr>
<tr>
<td>Voice / Texture</td>
<td>"deep and gravelly", "silky, mellow, and magnetic"</td>
</tr>
<tr>
<td>Mood / Tone</td>
<td>"warm and confident", "gentle but with a hint of weariness"</td>
</tr>
<tr>
<td>Speech speed / Rhythm</td>
<td>"slow and deliberate", "speaking at an extremely fast pace, like a machine gun."</td>
</tr>
</tbody>
</table>

The following dimensions can be optionally added to increase richness:

- **Role / Character**: narrator, podcast host, storyteller, late-night radio DJ

- **Speaking style**: casual and colloquial, seriously, lowering one's voice as if plotting

- **Scene description**: narrating a nature documentary, during a roadshow for investors

- **Era reference**: 1940s film noir, dubbed voices of translated films from the 1980s

#### Writing Suggestions

**Concise descriptive** -- quickly outline the sound profile using keywords or a single sentence

```bash
Heavy Russian accent, gruff middle-aged male, blunt and matter-of-fact.
```

**Professional Descriptive** -- Three-dimensional portrayal of sound through scenarios, character design, or multi-dimensional details

```bash
Young female, extreme close-up with a binaural, ear-to-ear ASMR feel. Audible breathing, subtle swallowing, and soft natural lip sounds. She speaks very slowly, creating a deeply relaxing and immersive experience.
```

```json
An elderly gentleman, speaking Mandarin with a northern accent, his speech slow and steady, his voice slightly hoarse and weathered, as if an old and seasoned grandfather were telling a story, full of the wisdom of years.
```

#### Precautions

- **Length**: 1-4 sentences are sufficient; there's no need to write a long text. Clearly describing the core features is more important than piling up dimensions

- **Avoid conflicts**: Do not simultaneously request contradictory characteristics (e.g., "innocent childish voice + CEO aura")

- **Avoid using audio quality effect terms**: Do not write descriptions related to post-processing such as reverb, echo, EQ, compression, etc

- **Avoid vague words**: Do not use descriptions lacking specific references such as "ordinary," "normal," or "foreign"

- **Both Chinese and English are supported**: the model supports both Chinese and English voice timbre descriptions, so choose the language in which you can express most precisely

- **Synthetic text should match the voice tone**: The synthetic text in the `assistant` message should match the voice tone description to achieve the best results. For example, pair a goodnight monologue with a "gentle and soothing female voice" instead of a passionate sports commentary. It is recommended to use LLM to automatically generate matching synthetic text based on your voice tone description; on the Studio page, you can directly click the "Generate Text" button after entering the voice tone description.

### Code Sample

<div className='mdx-highlight'>

`mimo-v2.5-tts-voicedesign` supports the optional parameter `optimize_text_preview` to control whether the target broadcast text is intelligently polished. When set to `true`, the `assistant` role message can be omitted.

</div>

#### Non-streaming Call

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-tts-voicedesign",
    "messages": [
        {
            "role": "user",
            "content": "Give me a young male tone."
        },
        {
            "role": "assistant",
            "content": "Yes, I had a sandwich."
        }
    ],
    "audio": {
        "format": "wav",
        "optimize_text_preview": true
    }
}'
```

**Python**

```python
import os
from openai import OpenAI
import base64

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

completion = client.chat.completions.create(
    model="mimo-v2.5-tts-voicedesign",
    messages=[
        {
            "role": "user",
            "content": "Give me a young male tone."
        },
        {
            "role": "assistant",
            "content": "Yes, I had a sandwich."
        }
    ],
    audio={
        "format": "wav",
        "optimize_text_preview": True
    }
)

message = completion.choices[0].message
audio_bytes = base64.b64decode(message.audio.data)
with open("audio_file.wav", "wb") as f:
    f.write(audio_bytes)
```

#### Streaming Call

<div className='mdx-highlight'>

- The low-latency streaming output feature of the MiMo-V2.5-TTS series is not yet available. If you have relevant requirements, please follow the upcoming feature updates.
- The streaming call interface is currently downgraded to compatibility mode, and only **returns the results once in streaming format after all inferences are completed.** 

</div>

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-tts-voicedesign",
    "messages": [
        {
            "role": "user",
            "content": "Give me a young male tone."
        },
        {
            "role": "assistant",
            "content": "You are UN-BE-LIEVABLE! I am sooooo done with your constant lies. GET. OUT!"
        }
    ],
    "audio": {
        "format": "pcm16",
        "optimize_text_preview": true
    },
    "stream": true
}'
```

**Python**

```python
import base64
import os
import numpy as np
import soundfile as sf
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

completion = client.chat.completions.create(
    model="mimo-v2.5-tts-voicedesign",
    messages=[
        {
            "role": "user",
            "content": "Give me a young male tone."
        },
        {
            "role": "assistant",
            "content": "You are UN-BE-LIEVABLE! I am sooooo done with your constant lies. GET. OUT!"
        }
    ],
    audio={
        "format": "pcm16",
        "optimize_text_preview": True
    },
    stream=True
)

# 24kHz PCM16LE mono audio
collected_chunks: np.ndarray = np.array([], dtype=np.float32)

for chunk in completion:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    audio = getattr(delta, "audio", None)

    if audio is not None:
        assert isinstance(audio, dict), f"Expected audio to be a dict, got {type(audio)}"
        pcm_bytes = base64.b64decode(audio["data"])
        np_pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        collected_chunks = np.concatenate((collected_chunks, np_pcm))
        print(f"Received audio chunk of size {len(pcm_bytes)} bytes")

# Save the collected audio to a file
os.makedirs("tmp", exist_ok=True)
sf.write("tmp/output.wav", collected_chunks, samplerate=24000)
print("Audio saved to tmp/output.wav")
```

## Speech Synthesis Using Voice Cloning

- By passing in audio samples, you can accurately replicate the target timbre and generate speech. Currently, only the `mimo-v2.5-tts-voiceclone` model is supported 

- Supports controlling the style of synthetic speech by passing natural language instructions in the user message

- Supports controlling the style of synthesized speech through audio tags 

### Code Sample

Convert the audio file sample to a Base64-encoded string and then pass it in. The size of the converted Base64-encoded string cannot exceed 10 MB, and currently only `mp3` and `wav` format audio sample files are supported.

<div className='mdx-highlight'>

**Precautions** 
- Please include the prefix before Base64 encoding:`data:{MIME_TYPE};base64,$BASE64_AUDIO`

- `{MIME_TYPE}`: The MIME type (media type) of the audio, used to identify the audio format, needs to be replaced with the MIME value corresponding to the actual audio. The values here can be: ` audio/mpeg ` (or ` audio/mp3 `), ` audio/wav `. 

- `$BASE64_AUDIO`: A pure Base64-encoded string of the audio file (without any prefix).

</div>

#### Non-streaming Call

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-tts-voiceclone",
    "messages": [
        {
            "role": "user",
            "content": ""
        },
        {
            "role": "assistant",
            "content": "Yes, I had a sandwich."
        }
    ],
    "audio": {
        "format": "wav",
        "voice": "data:{MIME_TYPE};base64,$BASE64_AUDIO"
    }
}'
```

**Python**

```python
import base64
import os

from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1",
)

with open("voice.mp3", "rb") as f:
    voice_bytes = f.read()
voice_base64 = base64.b64encode(voice_bytes).decode("utf-8")

completion = client.chat.completions.create(
    model="mimo-v2.5-tts-voiceclone",
    messages=[
        {
            "role": "user",
            "content": ""
        },
        {
            "role": "assistant", 
            "content": "Yes, I had a sandwich."
        }
    ],
    audio={
        "format": "wav",
        "voice": f"data:audio/mpeg;base64,{voice_base64}"
    }
)

message = completion.choices[0].message
audio_bytes = base64.b64decode(message.audio.data)
with open("audio_file.wav", "wb") as f:
    f.write(audio_bytes)
```

#### Streaming Call

<div className='mdx-highlight'>

- The low-latency streaming output feature of the MiMo-V2.5-TTS series is not yet available. If you have relevant requirements, please follow the upcoming feature updates.
- The streaming call interface is currently downgraded to compatibility mode, and only **returns** **the results oncein streaming formatafter all inferences are completed.** 

</div>

**Curl**

```bash
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "mimo-v2.5-tts-voiceclone",
    "messages": [
        {
            "role": "user",
            "content": ""
        },
        {
            "role": "assistant",
            "content": "You are UN-BE-LIEVABLE! I am sooooo done with your constant lies. GET. OUT!"
        }
    ],
    "audio": {
        "format": "pcm16",
        "voice": "data:{MIME_TYPE};base64,$BASE64_AUDIO"
    },
    "stream": true
}'
```

**Python**

```python
import base64
import os

import numpy as np
import soundfile as sf
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1",
)

with open("voice.mp3", "rb") as f:
    voice_bytes = f.read()
voice_base64 = base64.b64encode(voice_bytes).decode("utf-8")

completion = client.chat.completions.create(
    model="mimo-v2.5-tts-voiceclone",
    messages=[
        {
            "role": "user",
            "content": ""
        },
        {
            "role": "assistant", 
            "content": "Yes, I had a sandwich."
        }
    ],
    audio={
        "format": "wav",
        "voice": f"data:audio/mpeg;base64,{voice_base64}",
    },
    stream=True
)

# 24kHz PCM16LE mono audio
collected_chunks: np.ndarray = np.array([], dtype=np.float32)

for chunk in completion:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    audio = getattr(delta, "audio", None)

    if audio is not None:
        assert isinstance(audio, dict), (
            f"Expected audio to be a dict, got {type(audio)}"
        )
        pcm_bytes = base64.b64decode(audio["data"])
        np_pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        collected_chunks = np.concatenate((collected_chunks, np_pcm))
        print(f"Received audio chunk of size {len(pcm_bytes)} bytes")

# Save the collected audio to a file
os.makedirs("tmp", exist_ok=True)
sf.write("tmp/output.wav", collected_chunks, samplerate=24000)
print("Audio saved to tmp/output.wav")
```

## Price

- Billing: Free for a limited time.

- View Bill: You can view your usage on the [Billing](https://platform.xiaomimimo.com/#/console/usage) page in the Console.
