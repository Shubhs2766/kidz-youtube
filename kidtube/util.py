import json
import logging
import re
import subprocess
from pathlib import Path

import requests

log = logging.getLogger("kidtube.util")


class PipelineError(Exception):
    pass


def run(cmd: list[str], timeout: int = 1800) -> str:
    log.debug("run: %s", " ".join(map(str, cmd)))
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise PipelineError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd[:3]))}...\n{p.stderr[-1500:]}")
    return p.stdout


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    return json.loads(out)


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path)["streams"])


def download(url: str, out: Path, headers: dict | None = None, timeout: int = 300) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def extract_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def clean_text(s: str, limit: int) -> str:
    s = re.sub(r"[<>]", "", s or "").strip()
    return s[:limit]
