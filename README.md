# KidTube – automated kids' AI video channel

You drop a text file per day (`scripts/2026-09-29.txt`). KidTube:

1. reads that day's file → 2. Gemini turns it into a storyboard → 3. Veo renders each scene →
4. Gemini TTS adds narration and optional Lyria music → 5. FFmpeg assembles a 1080p 16:9 video → 6. Gemini checks frames for
child-safety/quality → 7. uploads to YouTube marked **Made for Kids** → 8. logs everything, stores history, sends alerts.

## 1. Install (once)
- Python 3.10+ and **FFmpeg** (`ffmpeg -version` must work; Windows: `winget install Gyan.FFmpeg`).
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows      (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

## 2. Test with no API keys (offline)
Put a short script of your own at `scripts/YYYY-MM-DD.txt`, then use the same date below. Script files are local inputs and are excluded from Git.
```bash
python -m kidtube run --dry-run --date YYYY-MM-DD
```
Makes a fake video with mock providers into `output/YYYY-MM-DD-dryrun/final.mp4`. If this works, the local install and assembly flow are working.

## 3. Test Gemini without hosted video or upload
1. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey).
2. Put it in `.env` as `GEMINI_API_KEY`.
3. Run a short live API test:
```bash
python -m kidtube run --api-test --date 2026-09-29
```
This uses the configured Gemini text model and TTS, local mock visuals, no music, and skips YouTube upload. Output goes to `output/2026-09-29-apitest/final.mp4`. QA failures are reported as failures; mock video is not representative of real Veo quality.

The API key must have quota for the selected models. Gemini free-tier quotas and model access vary by project; Veo, image output, and Lyria usage are paid and require billing.

## 4. Configure Google models
- Copy the blank `.env.example` to `.env`; put the single generative-model key in `GEMINI_API_KEY`.
- Configure model IDs and the daily cost ceiling in `config.yaml`. The default stack is Gemini Flash-Lite for text/vision, Gemini Flash-Lite TTS, Veo 3.1 Lite at 720p, Nano Banana Lite for optional image-to-video keyframes, and Lyria 3.5 music.
- The Google API key is shared across these models, but their billing and quotas are separate. Veo, generated images, and Lyria are paid; consult [COSTING.md](COSTING.md) before enabling image-to-video or raising resolution.
- Email alerts use SMTP settings in `.env`; `SMTP_PORT=465` uses implicit TLS, while port 587 uses STARTTLS. Success notifications require `alerts.min_level: info`.

## 5. YouTube access (once)
1. https://console.cloud.google.com → new project → enable **YouTube Data API v3**.
2. Configure Google Auth Platform. For initial testing, set the app to External and add your own Google account under Audience → Test users. Testing-mode refresh tokens expire after 7 days; production use requires completing Google's verification/audit requirements.
3. Credentials → Create OAuth client ID → **Desktop app** → download JSON → save as `secrets/client_secret.json`.
4. `python -m kidtube auth` → browser opens → choose the Google account **and the channel** → token saved to `secrets/token.json`.
5. **API audit:** uploads from unverified API projects are forced to private. Submit Google's "YouTube API Services – Audit and Quota Extension Form"
   for your project. Until it's approved, use `publish_mode: approval` and publish manually in YouTube Studio.
- Every upload sends `selfDeclaredMadeForKids: true` (and the synthetic-media flag). You are responsible for that declaration being accurate.

## 6. Check everything
```bash
python -m kidtube doctor
python -m kidtube run --date 2026-09-29          # one production run; uses Veo and uploads privately after QA
```

## 7. Run daily automatically – pick ONE
- **Always-on process:** `python -m kidtube serve` (runs at `schedule.time`, plus a watchdog alert and a weekly report). Use Docker/`systemd`/pm2 to keep it alive.
- **OS scheduler:** run `python -m kidtube run` daily via Windows Task Scheduler or cron, e.g. `0 9 * * * cd /path/kidtube && .venv/bin/python -m kidtube run`.
- **Docker:** `docker compose up -d --build` (mounts `scripts/`, `output/`, `data/`, `logs/`, `secrets/`).

## Daily use
- Add files named `YYYY-MM-DD.txt` (not `29/09/2026.txt` – slashes are not allowed in filenames) to `scripts/`. Free text; describe the whole video, characters, narration ideas.
- Spare scripts in `scripts/backlog/` are used automatically if a day's file is missing (you get a warning).
- `publish_mode: approval` → video is uploaded private; approve with `python -m kidtube publish 2026-09-29` (or in YouTube Studio).
  `scheduled` → private + YouTube's own `publishAt`; `auto` → public right away.
- `python -m kidtube status` shows history, worst-case cost reservations and errors. Rotating logs: `logs/kidtube.log`; generated assets: `output/<date>/`.

## Reliability built in
Resume-on-rerun (finished scenes/storyboard aren't paid for twice), stop-queuing after a scene failure, a cumulative worst-case cost guard before video rendering,
QA gate with one automatic regeneration of flagged scenes, Telegram/email alerts (critical on failure, missing script, QA hold, expired YouTube token),
watchdog alert if the run didn't finish, weekly report of missing next-week scripts, SQLite history in `data/kidtube.db`.

## Layout
`kidtube/` code · `config.yaml` settings · `.env` secrets · `scripts/` your local daily text files · `output/` videos + assets

## Known limits
Veo 3.1 Lite outputs 8-second 720p clips; FFmpeg upscales the final assembly to 1080p. Text prompts repeat character descriptions, but this does not guarantee perfect character continuity. Free-tier quota availability changes by project. See [COSTING.md](COSTING.md) for assumptions and limitations.
