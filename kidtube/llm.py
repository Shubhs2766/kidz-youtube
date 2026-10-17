import base64
import logging
from pathlib import Path

from .genai_client import get_client
from .util import extract_json

log = logging.getLogger("kidtube.llm")


def _client():
    return get_client()


def _call(model, max_tokens, system, content):
    parts = []
    for item in content:
        if item["type"] == "image":
            parts.append({"type": "image", "data": item["source"]["data"],
                          "mime_type": item["source"]["media_type"]})
        else:
            parts.append({"type": "text", "text": item["text"]})
    response = _client().interactions.create(
        model=model,
        system_instruction=system,
        input=[{"type": "user_input", "content": parts}],
        generation_config={"max_output_tokens": max_tokens},
        store=False,
    )
    return response.output_text or ""


def ask_json(cfg, system: str, user: str, images: list[Path] | None = None):
    content: list = []
    for p in images or []:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(Path(p).read_bytes()).decode()}})
    content.append({"type": "text", "text": user})
    model, mt = cfg["llm"]["model"], cfg["llm"].get("max_tokens", 6000)
    text = _call(model, mt, system, content)
    try:
        return extract_json(text)
    except Exception:
        log.warning("LLM returned invalid JSON, asking for a repair")
        fix = _call(model, mt, system, [{"type": "text", "text": "Return ONLY the valid JSON for this, nothing else:\n" + text}])
        return extract_json(fix)
