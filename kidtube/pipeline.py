"""End-to-end daily pipeline: script file -> storyboard -> clips -> audio -> assemble -> QA -> YouTube."""
import json
import logging
import shutil
import traceback
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from . import audio, assemble, qa, storyboard as sbmod, youtube
from .config import path_of, tz
from .db import DB, SUCCESS
from .notify import notify
from .providers import get_image_provider, get_video_provider
from .util import PipelineError, run

log = logging.getLogger("kidtube.pipeline")


class MissingScript(PipelineError):
    pass


def estimate_run_cost(cfg, scenes, video_provider, image_provider, image_to_video: bool) -> dict[str, float]:
    video_pass = sum(video_provider.estimate_cost(scene.seconds) for scene in scenes)
    attempts = max(1, int(cfg["video"].get("max_attempts", 1)))
    qa_enabled = cfg["qa"].get("enabled", True)
    qa_passes = 2 if qa_enabled and cfg["qa"].get("regenerate_failed_scenes", True) else 1 if qa_enabled else 0
    video = video_pass * attempts * qa_passes
    images = len(scenes) * image_provider.estimate_cost() * attempts if image_to_video else 0.0
    duration = sum(scene.seconds for scene in scenes)
    voice = duration * float(cfg["voice"].get("cost_per_second_usd", 0)) if cfg["voice"]["provider"] == "gemini" else 0.0
    music = float(cfg["music"].get("cost_per_generation_usd", 0)) if cfg["music"]["provider"] == "gemini" else 0.0
    llm_calls = 2 + qa_passes * 2  # storyboard and each QA pass may each request one JSON repair
    llm_qa = float(cfg["llm"].get("estimated_cost_per_call_usd", 0)) * llm_calls
    return {"video": video, "images": images, "voice": voice, "music": music,
            "llm_qa": llm_qa, "total": video + images + voice + music + llm_qa}


def resolve_script(cfg, date: str) -> tuple[Path, bool]:
    p = path_of(cfg, "scripts_dir") / f"{date}.txt"
    if p.exists():
        return p, False
    backlog = sorted(path_of(cfg, "backlog_dir").glob("*.txt"))
    if backlog:
        return backlog[0], True
    raise MissingScript(f"No script file {p.name} and the backlog is empty.")


def _thumb(cfg, video_norm: Path, out: Path) -> Path:
    from .util import duration_of
    t = duration_of(video_norm) / 2
    run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", video_norm, "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "3", out])
    return out


def _publish_at(cfg) -> str:
    hh, mm = map(int, cfg["youtube"]["publish_at_time"].split(":"))
    now = datetime.now(tz(cfg))
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= now + timedelta(minutes=20):
        t += timedelta(days=1)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_day(cfg, date: str, dry_run: bool = False, force: bool = False, api_test: bool = False) -> bool:
    if api_test:
        cfg = deepcopy(cfg)
        cfg["video"]["provider"] = "mock"
        cfg["image"]["provider"] = "mock"
        cfg["voice"].update(provider="gemini", voice_id="Kore", model_id="gemini-3.8-flash-lite-tts")
        cfg["music"]["provider"] = "none"
        cfg["content"].update(target_seconds=15, max_scene_seconds=5)
        cfg["qa"]["frames_per_scene"] = 1
    db = DB(path_of(cfg, "db_file"))
    prev = db.latest_run(date)
    if prev and prev["status"] in SUCCESS and not force and not dry_run and not api_test:
        log.info("Run for %s already finished (%s). Use --force to redo.", date, prev["status"])
        return True
    suffix = "-dryrun" if dry_run else "-apitest" if api_test else ""
    out = path_of(cfg, "output_dir") / (date + suffix)
    if force and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = None
    try:
        try:
            script_path, from_backlog = resolve_script(cfg, date)
        except MissingScript as e:
            notify(cfg, "critical", f"No script for {date}", str(e) + "\nNothing was published today.")
            raise
        if from_backlog:
            notify(cfg, "warning", f"Script for {date} missing; using backlog file {script_path.name}")
        run_id = db.start_run(date, str(script_path), dry_run or api_test)
        log.info("Run %s for %s using %s (dry_run=%s)", run_id, date, script_path.name, dry_run)
        text = script_path.read_text(encoding="utf-8")

        # 1. storyboard (resume if already generated)
        sb_file = out / "storyboard.json"
        if sb_file.exists():
            sb = sbmod.Storyboard.model_validate_json(sb_file.read_text(encoding="utf-8"))
        else:
            sb = sbmod.simple_storyboard(cfg, text) if dry_run else sbmod.build(cfg, text)
            sb_file.write_text(sb.model_dump_json(indent=2), encoding="utf-8")
        db.update_run(run_id, title=sb.youtube.title)

        vp, ip = get_video_provider(cfg, dry_run or api_test), get_image_provider(cfg, dry_run or api_test)
        costs = estimate_run_cost(cfg, sb.scenes, vp, ip, cfg["video"]["mode"] == "image_to_video")
        est = costs["total"]
        cap = float(cfg.get("limits", {}).get("max_daily_cost_usd", 1e9))
        prior_est = db.estimated_cost_for_date(date) if not dry_run and not api_test else 0.0
        if not dry_run and prior_est + est > cap:
            raise PipelineError(f"Prior worst-case estimate ${prior_est:.2f} plus this run's ${est:.2f} exceeds max_daily_cost_usd ${cap:.2f}; aborting before rendering.")
        db.update_run(run_id, est_cost=round(est, 2))
        log.info("Worst-case estimated cost $%.2f; prior production reserve $%.2f; daily cap $%.2f", est, prior_est, cap)

        # 2. render scenes
        raw, norm, aud = out / "scenes", out / "norm", out / "audio"
        for d in (raw, norm, aud):
            d.mkdir(exist_ok=True)
        i2v = cfg["video"]["mode"] == "image_to_video"
        abort_rendering = Event()

        def render(i: int, extra: str = ""):
            if abort_rendering.is_set():
                return
            sc = sb.scenes[i]
            dest = raw / f"scene_{i:02d}.mp4"
            if dest.exists():
                return
            prompt = sbmod.scene_prompt(cfg, sb, sc, extra)
            key = None
            if i2v:
                key = raw / f"key_{i:02d}.jpg"
            last = None
            max_attempts = max(1, int(cfg["video"].get("max_attempts", 1)))
            for attempt in range(1, max_attempts + 1):
                if abort_rendering.is_set():
                    return
                try:
                    db.upsert_scene(run_id, i, prompt=prompt, seconds=sc.seconds, status="rendering", attempts=attempt)
                    p = prompt if attempt == 1 else prompt + " Keep it extra gentle, simple and friendly."
                    if key is not None and not key.exists():
                        ip.generate(prompt, key)
                    vp.generate(p, sc.seconds, dest, key)
                    db.upsert_scene(run_id, i, status="done", path=str(dest), error=None)
                    return
                except Exception as e:  # noqa
                    last = e
                    log.warning("scene %d attempt %d failed: %s", i, attempt, e)
                    db.upsert_scene(run_id, i, status="retrying", error=str(e)[:500])
                    if attempt == max_attempts:
                        abort_rendering.set()
            db.upsert_scene(run_id, i, status="failed")
            raise PipelineError(f"Scene {i} failed after retries: {last}")

        def render_all(indices, extras=None):
            extras = extras or {}
            with ThreadPoolExecutor(max_workers=int(cfg["video"].get("max_parallel", 3))) as ex:
                futs = [ex.submit(render, i, extras.get(i, "")) for i in indices]
                errs = []
                for f in futs:
                    try:
                        f.result()
                    except Exception as e:  # noqa
                        errs.append(str(e))
                if errs:
                    raise PipelineError("; ".join(errs)[:1500])

        render_all(range(len(sb.scenes)))

        # 3. audio
        narr = {}
        audio_suffix = ".wav" if cfg["voice"]["provider"] == "gemini" else ".mp3"
        for i, sc in enumerate(sb.scenes):
            p = aud / f"narr_{i:02d}{audio_suffix}"
            if not p.exists():
                audio.narrate(cfg, sc.narration, p, dry_run)
            narr[i] = p if p.exists() else None
        total = sum(s.seconds for s in sb.scenes)
        music_file = aud / "music.mp3"
        music = music_file if music_file.exists() else audio.make_music(cfg, sb.music_prompt, total + 5, music_file, dry_run or api_test)

        # 4. assemble
        def build_final() -> dict[int, Path]:
            clips = {}
            for i in range(len(sb.scenes)):
                n = norm / f"scene_{i:02d}.mp4"
                assemble.normalize_scene(cfg, raw / f"scene_{i:02d}.mp4", narr[i], n, sb.scenes[i].seconds)
                clips[i] = n
            parts = []
            a = cfg["assemble"]
            intro = assemble.normalize_extra(cfg, a.get("intro_file", ""), out / "intro_n.mp4")
            outro = assemble.normalize_extra(cfg, a.get("outro_file", ""), out / "outro_n.mp4")
            parts = ([intro] if intro else []) + list(clips.values()) + ([outro] if outro else [])
            joined = assemble.concat(parts, out / "joined.mp4")
            assemble.add_music(cfg, joined, music, out / "final.mp4")
            return clips

        clips = build_final()
        final = out / "final.mp4"
        thumb = _thumb(cfg, clips[min(1, len(clips) - 1)], out / "thumb.jpg")

        # 5. QA
        qa_ok, qa_notes = True, ""
        if dry_run:
            log.info("dry-run: skipping QA and upload")
        elif cfg["qa"].get("enabled", True):
            problems = qa.technical_checks(cfg, final, total)
            res = qa.review(cfg, clips, out / "qa_frames")
            if (problems or not res["pass"]) and cfg["qa"].get("regenerate_failed_scenes", True):
                bad = sorted({int(x["scene"]) for x in res["issues"] if isinstance(x.get("scene"), int) and 0 <= int(x["scene"]) < len(sb.scenes)})
                if bad:
                    log.warning("QA failed scenes %s: %s; regenerating once", bad, res["issues"])
                    extras = {}
                    for x in res["issues"]:
                        if isinstance(x.get("scene"), int):
                            extras[int(x["scene"])] = "Fix this problem: " + str(x.get("problem"))
                    for i in bad:
                        (raw / f"scene_{i:02d}.mp4").unlink(missing_ok=True)
                    render_all(bad, extras)
                    clips = build_final()
                    problems = qa.technical_checks(cfg, final, total)
                    res = qa.review(cfg, clips, out / "qa_frames")
            (out / "qa.json").write_text(json.dumps({"technical": problems, **res}, indent=2), encoding="utf-8")
            qa_ok = not problems and res["pass"]
            qa_notes = "; ".join(problems + [f"scene {x.get('scene')}: {x.get('problem')}" for x in res["issues"]])

        if dry_run:
            db.finish(run_id, "dry_run_ok")
            log.info("Dry run finished OK -> %s", final)
            return True
        if api_test:
            status = "api_test_ok" if qa_ok else "api_test_qa_failed"
            db.finish(run_id, status, error=None if qa_ok else qa_notes[:1000])
            log.info("API test %s; upload skipped -> %s", "passed" if qa_ok else "failed QA", final)
            return qa_ok
        if not qa_ok and cfg["qa"].get("on_fail", "hold") == "hold":
            db.finish(run_id, "qa_failed", error=qa_notes[:1000])
            notify(cfg, "critical", f"QA failed for {date}: video NOT uploaded", f"{sb.youtube.title}\n{qa_notes}\nReview: {final}")
            return False

        # 6. upload
        y = cfg["youtube"]
        mode = y.get("publish_mode", "approval")
        privacy, publish_at, status = "public", None, "published"
        if mode == "approval" or not qa_ok:
            privacy, status = "private", "awaiting_approval"
        elif mode == "scheduled":
            privacy, publish_at, status = "private", _publish_at(cfg), "scheduled"
        youtube.check_channel(cfg)
        vid = youtube.upload(cfg, final, sb.youtube.title, sb.youtube.description, sb.youtube.tags, privacy, publish_at, thumb)
        url = f"https://youtu.be/{vid}"
        db.finish(run_id, status, video_id=vid, video_url=url, privacy=privacy)
        extra = {"published": "It is PUBLIC now.", "awaiting_approval": "Private: approve with `python -m kidtube publish " + date + "`.",
                 "scheduled": f"Private, goes public at {publish_at}."}[status]
        notify(cfg, "info" if qa_ok else "warning", f"Video ready for {date}: {sb.youtube.title}", f"{url}\n{extra}\nEst. cost ${est:.2f}" + ("" if qa_ok else f"\nQA warnings: {qa_notes}"))
        if from_backlog:
            used = script_path.parent / "used"
            used.mkdir(exist_ok=True)
            shutil.move(str(script_path), str(used / script_path.name))
        return True
    except MissingScript:
        return False
    except Exception as e:  # noqa
        log.error("Run failed: %s", e, exc_info=True)
        if run_id:
            db.finish(run_id, "failed", error=str(e)[:1500])
        notify(cfg, "critical", f"Run FAILED for {date}", f"{e}\n\n{traceback.format_exc()[-1200:]}")
        return False


def publish_video(cfg, date: str) -> None:
    db = DB(path_of(cfg, "db_file"))
    r = db.latest_run(date)
    if not r or not r["video_id"]:
        raise PipelineError(f"No uploaded video found for {date}")
    youtube.publish(cfg, r["video_id"])
    db.update_run(r["id"], status="published", privacy="public")
    notify(cfg, "info", f"Published {date}: {r['title']}", r["video_url"] or "")
