"""Offline providers for --dry-run / tests: synthetic clips and images made with ffmpeg."""
import random

from ..util import run
from .base import ImageProvider, VideoProvider


class MockVideo(VideoProvider):
    def generate(self, prompt, seconds, out_path, image_path=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        color = random.choice(["0x2b8fe6", "0xff8a3d", "0x47c98a", "0xb08cff"])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1280x720:r=24:d={seconds}",
             "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", out_path])


class MockImage(ImageProvider):
    def generate(self, prompt, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x66ccff:s=1280x720:d=1", "-frames:v", "1", out_path])
