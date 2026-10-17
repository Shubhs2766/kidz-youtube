import logging
from pathlib import Path

from .util import duration_of, has_audio, run

log = logging.getLogger("kidtube.assemble")


def _scale(cfg):
    a = cfg["assemble"]
    w, h, fps = a["width"], a["height"], a["fps"]
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p")


def normalize_scene(cfg, clip: Path, narration: Path | None, out: Path, target_seconds: float | None = None) -> Path:
    """Scale/pad clip to the target size, mix optional narration (+ native audio), always output aac stereo."""
    dur = duration_of(clip)
    if target_seconds is not None:
        dur = min(dur, float(target_seconds))
    use_native = cfg["video"].get("use_native_audio", False) and has_audio(clip)
    nv = float(cfg["video"].get("native_audio_volume", 0.5))
    vv = float(cfg["voice"].get("volume", 1.0))
    cmd = ["ffmpeg", "-y", "-i", clip, "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    if narration:
        cmd += ["-i", narration]
    fc = [f"[0:v]{_scale(cfg)}[v]"]
    labels = []
    if use_native:
        fc.append(f"[0:a]aresample=44100,volume={nv}[na]")
        labels.append("[na]")
    else:
        labels.append("[1:a]")
    if narration:
        fc.append(f"[2:a]aresample=44100,adelay=400|400,volume={vv}[nr]")
        labels.append("[nr]")
    if len(labels) > 1:
        fc.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,atrim=0:{dur:.3f},aformat=channel_layouts=stereo[a]")
    else:
        fc.append(f"{labels[0]}atrim=0:{dur:.3f},aformat=channel_layouts=stereo[a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{dur:.3f}", out]
    run(cmd)
    return out


def concat(parts: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    return out


def add_music(cfg, video: Path, music: Path | None, out: Path) -> Path:
    if not music:
        run(["ffmpeg", "-y", "-i", video, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out])
        return out
    mv = float(cfg["music"].get("volume", 0.22))
    dur = duration_of(video)
    fade_st = max(0.0, dur - 2.5)
    run(["ffmpeg", "-y", "-i", video, "-stream_loop", "-1", "-i", music, "-filter_complex",
         f"[1:a]aresample=44100,volume={mv},afade=t=out:st={fade_st:.2f}:d=2.5[m];"
         f"[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", out])
    return out


def normalize_extra(cfg, src: str, out: Path) -> Path | None:
    if not src or not Path(src).exists():
        return None
    run(["ffmpeg", "-y", "-i", src, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
         f"[0:v]{_scale(cfg)}[v]", "-map", "[v]", "-map", "1:a", "-shortest", "-c:v", "libx264", "-crf", "18",
         "-c:a", "aac", "-ar", "44100", out])
    return out


def extract_frames(video: Path, n: int, out_dir: Path, prefix: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    d = duration_of(video)
    frames = []
    for i in range(n):
        t = d * (i + 1) / (n + 1)
        p = out_dir / f"{prefix}_{i}.jpg"
        run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", p])
        frames.append(p)
    return frames
