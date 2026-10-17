import logging
import time
from pathlib import Path

from .config import ROOT
from .util import PipelineError

log = logging.getLogger("kidtube.youtube")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def _p(cfg, key) -> Path:
    p = Path(cfg["youtube"][key])
    return p if p.is_absolute() else ROOT / p


def authorize(cfg) -> None:
    """One-time interactive OAuth: opens a browser, you pick the Google account/channel, token is saved."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    secret = _p(cfg, "client_secret_file")
    if not secret.exists():
        raise PipelineError(f"OAuth client file not found: {secret}. See README step 4.")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    tok = _p(cfg, "token_file")
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text(creds.to_json(), encoding="utf-8")
    log.info("Saved YouTube token to %s", tok)


def get_service(cfg):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    tok = _p(cfg, "token_file")
    if not tok.exists():
        raise PipelineError("YouTube not authorized yet. Run: python -m kidtube auth")
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
            tok.write_text(creds.to_json(), encoding="utf-8")
        except RefreshError as e:
            raise PipelineError(f"YouTube authorization expired/revoked ({e}). Run: python -m kidtube auth") from e
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_info(cfg) -> dict:
    yt = get_service(cfg)
    items = yt.channels().list(part="id,snippet", mine=True).execute().get("items", [])
    if not items:
        raise PipelineError("Authorized Google account has no YouTube channel.")
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}


def check_channel(cfg) -> None:
    want = cfg["youtube"].get("channel_id", "")
    info = channel_info(cfg)
    if want and want != info["id"]:
        raise PipelineError(f"Authorized channel is {info['id']} ({info['title']}) but config expects {want}. Re-run auth and pick the right channel.")
    log.info("YouTube channel: %s (%s)", info["title"], info["id"])


def upload(cfg, video: Path, title, description, tags, privacy: str, publish_at: str | None = None, thumb: Path | None = None) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    y = cfg["youtube"]
    yt = get_service(cfg)
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(y.get("made_for_kids", True)),
              "containsSyntheticMedia": bool(y.get("contains_synthetic_media", True))}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    body = {"snippet": {"title": title, "description": description, "tags": tags, "categoryId": str(y.get("category_id", "1")),
                        "defaultLanguage": y.get("default_language", "en")}, "status": status}
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, tries = None, 0
    while resp is None:
        try:
            st, resp = req.next_chunk()
            if st:
                log.info("upload %d%%", int(st.progress() * 100))
        except HttpError as e:
            code = e.resp.status
            reason = str(e)
            if code in (500, 502, 503, 504) and tries < 6:
                tries += 1
                time.sleep(2 ** tries)
                continue
            if code == 403 and ("quota" in reason.lower() or "uploadLimit" in reason):
                raise PipelineError(f"YouTube quota/upload limit reached: {reason[:300]}") from e
            raise PipelineError(f"YouTube upload failed ({code}): {reason[:400]}") from e
    vid = resp["id"]
    log.info("uploaded video id %s (%s)", vid, status["privacyStatus"])
    if thumb and thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
        except Exception as e:  # channel may need phone verification for custom thumbnails
            log.warning("thumbnail not set: %s", e)
    return vid


def publish(cfg, video_id: str) -> None:
    yt = get_service(cfg)
    status = {"privacyStatus": "public", "selfDeclaredMadeForKids": bool(cfg["youtube"].get("made_for_kids", True)),
              "containsSyntheticMedia": bool(cfg["youtube"].get("contains_synthetic_media", True))}
    yt.videos().update(part="status", body={"id": video_id, "status": status}).execute()
    log.info("video %s is now public", video_id)
