"""Runtime settings, read once from the environment."""

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    version: str
    api_token: str
    max_upload_mb: int
    max_pages: int
    max_render_dpi: int
    max_render_pages: int
    max_render_megapixels: int
    max_concurrent_jobs: int
    font_path: str

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load() -> Settings:
    return Settings(
        version=os.environ.get("APP_VERSION", "dev"),
        api_token=os.environ.get("API_TOKEN", "").strip(),
        max_upload_mb=_int("MAX_UPLOAD_MB", 100),
        max_pages=_int("MAX_PAGES", 5000),
        max_render_dpi=_int("MAX_RENDER_DPI", 300),
        max_render_pages=_int("MAX_RENDER_PAGES", 200),
        max_render_megapixels=_int("MAX_RENDER_MEGAPIXELS", 40),
        max_concurrent_jobs=_int("MAX_CONCURRENT_JOBS", 4),
        font_path=os.environ.get("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )


settings = load()
