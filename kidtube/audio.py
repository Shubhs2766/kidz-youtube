import base64
import logging
import random
from pathlib import Path

from .config import path_of
from .genai_client import get_client
from .util import PipelineError, run

log = logging.getLogger("kidtube.audio")


def _gemini_tts(text: str, voice_id: str, model_id: str, out: Path) -> None:
    response = get_client().interactions.create(
        model=model_id,
        input=[{"type": "user_input", "content": [{
            "type": "text", "text": text,
            "annotations": [{"type": "speech_metadata", "style": "warm, friendly and cheerful"}],
        }]}],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": voice_id}]},
        store=False,
    )
    out.write_bytes(base64.b64decode(response.output_audio.data))


def narrate(cfg, text: str, out: Path, dry_run=False) -> Path | None:
    v = cfg["voice"]
    text = (text or "").strip()
    if not text or v["provider"] == "none":
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    if dry_run or v["provider"] == "mock":
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-c:a", "libmp3lame", out])
        return out
    if v["provider"] == "gemini":
        _gemini_tts(text, v.get("voice_id", "Kore"), v.get("model_id", "gemini-3.8-flash-tts"), out)
    else:
        raise ValueError(f"Unknown voice provider {v['provider']}")
    return out


def make_music(cfg, prompt: str, seconds: float, out: Path, dry_run=False) -> Path | None:
    m = cfg["music"]
    if dry_run or m["provider"] == "none":
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    if m["provider"] == "file":
        files = [p for p in path_of(cfg, "music_library_dir").glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a")]
        if not files:
            log.warning("music.provider=file but no tracks in %s; continuing without music", path_of(cfg, "music_library_dir"))
            return None
        return random.choice(files)
    if m["provider"] == "gemini":
        full = f"{prompt}. {m.get('prompt_suffix', '')}".strip()
        response = get_client().interactions.create(
            model=m.get("model_id", "lyria-3.5"), input=full, store=False,
        )
        generated = getattr(response, "output_audio", None)
        if not generated or not generated.data:
            raise PipelineError("Lyria music generation returned no audio.")
        out.write_bytes(base64.b64decode(generated.data))
        return out
    raise ValueError(f"Unknown music provider {m['provider']}")
