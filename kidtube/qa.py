import logging
from pathlib import Path

from .assemble import extract_frames
from .llm import ask_json
from .util import duration_of, probe

log = logging.getLogger("kidtube.qa")

SYSTEM = """You are a strict child-safety and quality reviewer for a YouTube channel for {audience}.
You receive sampled frames from an AI-generated cartoon video, each labelled with its scene number.
Fail a scene if you see: anything scary, violent, sad or age-inappropriate; readable text, logos or watermarks;
recognizable copyrighted characters; badly distorted faces/limbs/objects; a character that looks very different from the others.
Reply with ONLY JSON: {{"pass": bool, "issues": [{{"scene": int, "problem": str}}]}}. If everything is fine: {{"pass": true, "issues": []}}."""


def technical_checks(cfg, video: Path, expected_seconds: float) -> list[str]:
    problems = []
    info = probe(video)
    streams = info["streams"]
    if not any(s["codec_type"] == "video" for s in streams):
        problems.append("no video stream")
    if not any(s["codec_type"] == "audio" for s in streams):
        problems.append("no audio stream")
    d = duration_of(video)
    if d < expected_seconds * 0.6:
        problems.append(f"video too short ({d:.0f}s vs ~{expected_seconds:.0f}s)")
    return problems


def review(cfg, scene_clips: dict[int, Path], work: Path) -> dict:
    """scene_clips: {scene_index: normalized clip}. Returns {"pass": bool, "issues": [...]}."""
    frames, labels = [], []
    for idx, clip in scene_clips.items():
        for f in extract_frames(clip, int(cfg["qa"].get("frames_per_scene", 2)), work, f"s{idx}"):
            frames.append(f)
            labels.append(f"scene {idx}")
    user = "Frames in order: " + ", ".join(f"image {i + 1} = {l}" for i, l in enumerate(labels))
    res = ask_json(cfg, SYSTEM.format(audience=cfg["content"]["audience"]), user, images=frames)
    res.setdefault("issues", [])
    res["pass"] = bool(res.get("pass")) and not res["issues"]
    return res
