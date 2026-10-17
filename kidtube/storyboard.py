import logging
import re

from pydantic import BaseModel, Field, field_validator

from .llm import ask_json
from .util import clean_text

log = logging.getLogger("kidtube.storyboard")


class Character(BaseModel):
    id: str
    name: str = ""
    description: str


class Scene(BaseModel):
    prompt: str
    seconds: float = 5
    narration: str = ""
    characters: list[str] = Field(default_factory=list)


class YT(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _t(cls, v):
        return v or []


class Storyboard(BaseModel):
    title: str
    style_guide: str = ""
    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene]
    music_prompt: str = "cheerful preschool music"
    youtube: YT

    @field_validator("scenes")
    @classmethod
    def _s(cls, v):
        if not v:
            raise ValueError("no scenes")
        return v


SYSTEM = """You are the head storyboard artist for a children's YouTube channel of AI-generated 3D animated videos.
Audience: {audience}. Language: {language}.
Turn the user's script into a production storyboard and reply with ONLY one JSON object (no markdown) of this shape:
{{
 "title": str,
 "style_guide": str,                       // one paragraph of visual style, reused for every scene
 "characters": [{{"id": str, "name": str, "description": str}}],   // detailed, fixed visual descriptions (colors, shapes, features)
 "scenes": [{{"prompt": str, "seconds": number, "narration": str, "characters": [character ids]}}],
 "music_prompt": str,                      // instrumental music description
 "youtube": {{"title": str (<=90 chars, no clickbait), "description": str, "tags": [str]}}
}}
Rules:
- Total duration about {target} seconds; each scene at most {max_scene} seconds; usually {n_min}-{n_max} scenes.
- Each scene "prompt" must be self-contained: describe setting, action, camera move and lighting; re-describe characters via their id (do not rely on other scenes).
- Absolutely child-safe: nothing scary, violent, sad-ending, or age-inappropriate. No on-screen text, logos, brands or real people. No copyrighted characters, songs or melodies; everything original.
- Movements large, simple, repetitive and synchronized with music, easy for young children to follow.
- "narration" is short, warm, simple sentences read aloud (may be empty for purely musical scenes). Keep under ~{words} words per scene.
- Scene prompts must not ask for spoken dialogue lip-sync; narration is added separately.
"""


def build(cfg, script_text: str) -> Storyboard:
    c = cfg["content"]
    target, mx = int(c["target_seconds"]), int(c["max_scene_seconds"])
    system = SYSTEM.format(audience=c["audience"], language=c["language"], target=target, max_scene=mx,
                           n_min=max(3, target // mx), n_max=max(4, target // 4), words=max(8, int(mx * 2.2)))
    data = ask_json(cfg, system, "SCRIPT:\n" + script_text)
    sb = Storyboard.model_validate(data)
    return finalize(cfg, sb)


def finalize(cfg, sb: Storyboard) -> Storyboard:
    c = cfg["content"]
    mx = float(c["max_scene_seconds"])
    for s in sb.scenes:
        s.seconds = max(3.0, min(mx, float(s.seconds)))
    sb.title = clean_text(sb.title, 100)
    sb.youtube.title = clean_text(sb.youtube.title or sb.title, 100)
    footer = c.get("description_footer", "")
    sb.youtube.description = clean_text((sb.youtube.description + "\n\n" + footer).strip(), 4900)
    tags, total = [], 0
    for t in sb.youtube.tags:
        t = clean_text(t, 30).replace(",", "")
        if t and total + len(t) < 450:
            tags.append(t)
            total += len(t) + 1
    sb.youtube.tags = tags
    if not sb.style_guide:
        sb.style_guide = c["style_guide"]
    return sb


def simple_storyboard(cfg, script_text: str) -> Storyboard:
    """Offline storyboard used by --dry-run (no LLM)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", script_text) if p.strip()][:6] or [script_text[:200]]
    scenes = [Scene(prompt=p[:400], seconds=5, narration=p[:80]) for p in paras]
    title = paras[0].splitlines()[0][:80]
    return finalize(cfg, Storyboard(title=title, scenes=scenes, youtube=YT(title=title, description=script_text[:300], tags=["kids"])))


def scene_prompt(cfg, sb: Storyboard, sc: Scene, extra: str = "") -> str:
    chars = {c.id: c for c in sb.characters}
    cdesc = " ".join(f"{chars[i].name or i}: {chars[i].description}." for i in sc.characters if i in chars)
    parts = [sb.style_guide or cfg["content"]["style_guide"], cdesc, sc.prompt, "Avoid: " + cfg["content"]["negative_rules"] + "."]
    if extra:
        parts.append(extra)
    return " ".join(p for p in parts if p)[:2400]
