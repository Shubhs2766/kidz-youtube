"""Gemini image and Veo video generation using the shared Google API key."""
import base64
import time
from pathlib import Path

from ..genai_client import get_client
from ..util import PipelineError
from .base import ImageProvider, VideoProvider


class GeminiVideo(VideoProvider):
    def __init__(self, cfg):
        self.v = cfg["video"]

    def billed_seconds(self, seconds: float) -> float:
        return 8

    def estimate_cost(self, seconds: float) -> float:
        return self.billed_seconds(seconds) * float(self.v.get("cost_per_second_usd", 0))

    def generate(self, prompt, seconds, out_path, image_path=None):
        from google.genai import types

        config = types.GenerateVideosConfig(
            aspect_ratio=self.v.get("aspect_ratio", "16:9"),
            duration_seconds=8,
            resolution=self.v.get("resolution", "720p"),
            number_of_videos=1,
            generate_audio=bool(self.v.get("generate_audio", True)),
        )
        kwargs = {"model": self.v["model"], "prompt": prompt, "config": config}
        if image_path is not None:
            kwargs["image"] = types.Image.from_file(location=str(image_path))

        client = get_client()
        operation = client.models.generate_videos(**kwargs)
        deadline = time.monotonic() + int(self.v.get("timeout_seconds", 900))
        while not operation.done:
            if time.monotonic() >= deadline:
                raise PipelineError("Veo generation timed out before completion.")
            time.sleep(int(self.v.get("poll_seconds", 10)))
            operation = client.operations.get(operation)

        if operation.error:
            raise PipelineError(f"Veo generation failed: {operation.error}")
        response = operation.response
        generated = getattr(response, "generated_videos", None) if response else None
        if not generated:
            raise PipelineError("Veo completed without returning a video.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        client.files.download(file=generated[0].video, destination=out_path)


class GeminiImage(ImageProvider):
    def __init__(self, cfg):
        self.i = cfg["image"]

    def estimate_cost(self) -> float:
        return float(self.i.get("cost_per_image_usd", 0))

    def generate(self, prompt, out_path):
        response = get_client().interactions.create(
            model=self.i["model"],
            input=prompt,
            response_format={
                "type": "image",
                "mime_type": "image/jpeg",
                "aspect_ratio": self.i.get("aspect_ratio", "16:9"),
                "image_size": self.i.get("image_size", "1K"),
            },
            store=False,
        )
        image = getattr(response, "output_image", None)
        if not image or not image.data:
            raise PipelineError("Gemini image generation returned no image.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(image.data))
