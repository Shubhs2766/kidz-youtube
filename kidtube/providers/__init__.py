from .base import ImageProvider, VideoProvider
from .gemini import GeminiImage, GeminiVideo
from .mock import MockImage, MockVideo


def get_video_provider(cfg, dry_run=False) -> VideoProvider:
    name = "mock" if dry_run else cfg["video"]["provider"]
    if name == "gemini":
        return GeminiVideo(cfg)
    if name == "mock":
        return MockVideo()
    raise ValueError(f"Unknown video provider '{name}'. Add an adapter in kidtube/providers/ and register it here.")


def get_image_provider(cfg, dry_run=False) -> ImageProvider:
    name = "mock" if dry_run else cfg["image"]["provider"]
    if name == "gemini":
        return GeminiImage(cfg)
    if name == "mock":
        return MockImage()
    raise ValueError(f"Unknown image provider '{name}'")
