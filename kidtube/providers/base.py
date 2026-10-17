from pathlib import Path


class VideoProvider:
    """Blocking interface: generate one clip and save it to out_path."""

    def generate(self, prompt: str, seconds: float, out_path: Path, image_path: Path | None = None) -> None:
        raise NotImplementedError

    def billed_seconds(self, seconds: float) -> float:
        return seconds

    def estimate_cost(self, seconds: float) -> float:
        return 0.0


class ImageProvider:
    def generate(self, prompt: str, out_path: Path) -> None:
        raise NotImplementedError

    def estimate_cost(self) -> float:
        return 0.0
