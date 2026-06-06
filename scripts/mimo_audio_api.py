#!/usr/bin/env python3
"""Xiaomi Mimo ASR/TTS helper for YouTube dubbing jobs.

Uses only Python standard library. Set MIMO_TOKEN_PLAN_API_KEY in .env before live calls.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
TOKEN_PLAN_API_KEY_ENV = "MIMO_TOKEN_PLAN_API_KEY"
LEGACY_API_KEY_ENV = "MIMO_API_KEY"
MAX_BASE64_BYTES = 10 * 1024 * 1024


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_text_arg(value: str) -> str:
    if value.startswith("@"):
        return Path(value[1:]).expanduser().read_text(encoding="utf-8").strip()
    return value


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def mime_for_audio(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    guessed = mimetypes.guess_type(str(path))[0]
    if guessed in {"audio/wav", "audio/mpeg", "audio/mp3"}:
        return guessed
    raise SystemExit(f"Unsupported audio format for Mimo: {path}. Use wav or mp3.")


def audio_data_url(path: Path) -> tuple[str, int]:
    data = path.expanduser().read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    if len(encoded.encode("ascii")) > MAX_BASE64_BYTES:
        raise SystemExit(
            f"Base64 audio is {len(encoded.encode('ascii'))} bytes, above Mimo's 10 MB limit. "
            "Split or compress the audio first."
        )
    return f"data:{mime_for_audio(path)};base64,{encoded}", len(encoded.encode("ascii"))


def dry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(payload, ensure_ascii=False))
    for message in copied.get("messages", []):
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                input_audio = part.get("input_audio") if isinstance(part, dict) else None
                if isinstance(input_audio, dict) and "data" in input_audio:
                    input_audio["data"] = "data:audio/wav;base64,<omitted>"
    audio = copied.get("audio")
    if isinstance(audio, dict) and isinstance(audio.get("voice"), str) and audio["voice"].startswith("data:"):
        audio["voice"] = "data:audio/wav;base64,<omitted>"
    return copied


def mimo_post(payload: dict[str, Any], *, base_url: str, api_key: str, retries: int = 5) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=420) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                delay = min(60, 2 ** attempt * 3)
                print(f"Mimo HTTP {exc.code}; retrying in {delay}s", file=sys.stderr, flush=True)
                time.sleep(delay)
                continue
            raise SystemExit(f"Mimo API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, ssl.SSLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            if attempt + 1 < retries:
                delay = min(60, 2 ** attempt * 3)
                print(f"Mimo network error {exc}; retrying in {delay}s", file=sys.stderr, flush=True)
                time.sleep(delay)
                continue
            raise SystemExit(f"Mimo API request failed: {exc}") from exc

    raise SystemExit("Mimo API retry loop exhausted.")


def api_config(args: argparse.Namespace) -> tuple[str, str]:
    base_url = args.base_url or os.environ.get("MIMO_API_BASE_URL") or DEFAULT_BASE_URL
    api_key = args.api_key or os.environ.get(TOKEN_PLAN_API_KEY_ENV) or os.environ.get(LEGACY_API_KEY_ENV) or ""
    if not args.dry_run and not api_key:
        raise SystemExit(f"{TOKEN_PLAN_API_KEY_ENV} is required in .env or the environment.")
    return base_url, api_key


def extract_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        return response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit("Unexpected Mimo response shape; inspect raw output.") from exc


def check(args: argparse.Namespace) -> None:
    payload = {
        TOKEN_PLAN_API_KEY_ENV: "set" if os.environ.get(TOKEN_PLAN_API_KEY_ENV) else "missing",
        LEGACY_API_KEY_ENV: "set" if os.environ.get(LEGACY_API_KEY_ENV) else "missing",
        "MIMO_API_BASE_URL": os.environ.get("MIMO_API_BASE_URL") or DEFAULT_BASE_URL,
    }
    print(json.dumps(payload, indent=2))


def asr(args: argparse.Namespace) -> None:
    data_url, encoded_size = audio_data_url(Path(args.audio))
    payload = {
        "model": "mimo-v2.5-asr",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": data_url,
                        },
                    }
                ],
            }
        ],
        "asr_options": {
            "language": args.language,
        },
    }
    if args.dry_run:
        print(json.dumps({"base64_size": encoded_size, "payload": dry_payload(payload)}, indent=2, ensure_ascii=False))
        return

    base_url, api_key = api_config(args)
    response = mimo_post(payload, base_url=base_url, api_key=api_key)
    if args.raw_output:
        write_json(Path(args.raw_output), response)
    message = extract_message(response)
    transcript = message.get("content")
    if not isinstance(transcript, str):
        raise SystemExit("ASR response did not include choices[0].message.content as text.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(transcript, encoding="utf-8")
    print(f"Wrote {output}")


def tts_payload(args: argparse.Namespace) -> dict[str, Any]:
    text = read_text_arg(args.text)
    style_prompt = read_text_arg(args.style_prompt) if args.style_prompt else ""
    messages: list[dict[str, str]] = []

    if args.strategy == "built-in":
        if style_prompt:
            messages.append({"role": "user", "content": style_prompt})
        messages.append({"role": "assistant", "content": text})
        return {
            "model": "mimo-v2.5-tts",
            "messages": messages,
            "audio": {
                "format": args.format,
                "voice": args.voice,
            },
        }

    if args.strategy == "voice-design":
        if not args.voice_design_prompt:
            raise SystemExit("--voice-design-prompt is required for voice-design strategy.")
        messages.append({"role": "user", "content": read_text_arg(args.voice_design_prompt)})
        messages.append({"role": "assistant", "content": text})
        return {
            "model": "mimo-v2.5-tts-voicedesign",
            "messages": messages,
            "audio": {
                "format": args.format,
                "optimize_text_preview": bool(args.optimize_text_preview),
            },
        }

    if args.strategy == "voice-clone":
        if not args.voice_sample:
            raise SystemExit("--voice-sample is required for voice-clone strategy.")
        sample_data_url, _ = audio_data_url(Path(args.voice_sample))
        messages.append({"role": "user", "content": style_prompt})
        messages.append({"role": "assistant", "content": text})
        return {
            "model": "mimo-v2.5-tts-voiceclone",
            "messages": messages,
            "audio": {
                "format": args.format,
                "voice": sample_data_url,
            },
        }

    raise SystemExit(f"Unknown strategy: {args.strategy}")


def tts(args: argparse.Namespace) -> None:
    payload = tts_payload(args)
    if args.dry_run:
        print(json.dumps(dry_payload(payload), indent=2, ensure_ascii=False))
        return

    base_url, api_key = api_config(args)
    response = mimo_post(payload, base_url=base_url, api_key=api_key)
    if args.raw_output:
        write_json(Path(args.raw_output), response)
    message = extract_message(response)
    audio = message.get("audio")
    if not isinstance(audio, dict) or not isinstance(audio.get("data"), str):
        raise SystemExit("TTS response did not include choices[0].message.audio.data.")
    audio_bytes = base64.b64decode(audio["data"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio_bytes)
    print(f"Wrote {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help=f"Mimo API base URL; defaults to {DEFAULT_BASE_URL}")
    parser.add_argument("--api-key", help=f"Mimo API key; defaults to {TOKEN_PLAN_API_KEY_ENV}")
    parser.add_argument("--env-file", default=".env", help="Env file to load before live calls")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Inspect Mimo environment")
    check_parser.set_defaults(func=check, dry_run=True)

    asr_parser = subparsers.add_parser("asr", help="Call Mimo ASR")
    asr_parser.add_argument("--audio", required=True, help="WAV or MP3 file")
    asr_parser.add_argument("--language", default="en", choices=["auto", "zh", "en"])
    asr_parser.add_argument("--output", required=True, help="Transcript text output path")
    asr_parser.add_argument("--raw-output", help="Raw JSON response output path")
    asr_parser.add_argument("--dry-run", action="store_true")
    asr_parser.set_defaults(func=asr)

    tts_parser = subparsers.add_parser("tts", help="Call Mimo TTS")
    tts_parser.add_argument("--strategy", required=True, choices=["built-in", "voice-design", "voice-clone"])
    tts_parser.add_argument("--text", required=True, help="Text to synthesize, or @path")
    tts_parser.add_argument("--output", required=True, help="Audio output path")
    tts_parser.add_argument("--raw-output", help="Raw JSON response output path")
    tts_parser.add_argument("--format", default="wav", choices=["wav", "pcm16"])
    tts_parser.add_argument("--style-prompt", help="Optional style guidance, or @path")
    tts_parser.add_argument("--voice", default="mimo_default", help="Built-in voice for built-in strategy")
    tts_parser.add_argument("--voice-design-prompt", help="Voice design prompt, or @path")
    tts_parser.add_argument("--voice-sample", help="WAV or MP3 sample for voice-clone strategy")
    tts_parser.add_argument("--optimize-text-preview", action="store_true")
    tts_parser.add_argument("--dry-run", action="store_true")
    tts_parser.set_defaults(func=tts)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.env_file:
        load_env_file(Path(args.env_file).expanduser())
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
