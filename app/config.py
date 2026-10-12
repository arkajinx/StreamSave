import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class Settings:
    download_dir: Path
    max_duration: int = 3600
    max_file_bytes: int = 500 * 1024 * 1024
    max_storage_bytes: int = 2048 * 1024 * 1024
    min_free_bytes: int = 256 * 1024 * 1024
    max_concurrent: int = 1
    max_jobs: int = 16
    max_inspections: int = 256
    max_requests_per_minute: int = 12
    inspection_ttl: int = 600
    file_ttl: int = 1800
    inspection_timeout: int = 45
    download_timeout: int = 600
    secure_cookies: bool = False
    public_url: str = ""
    cobalt_api_url: str = "http://127.0.0.1:9000/"
    cobalt_api_key: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            download_dir=Path(os.getenv("DOWNLOAD_DIR", "./data/downloads")).resolve(),
            max_duration=positive_int("MAX_DURATION_SECONDS", 3600),
            max_file_bytes=positive_int("MAX_FILE_MB", 500) * 1024 * 1024,
            max_storage_bytes=positive_int("MAX_STORAGE_MB", 2048) * 1024 * 1024,
            min_free_bytes=positive_int("MIN_FREE_MB", 256) * 1024 * 1024,
            max_concurrent=positive_int("MAX_CONCURRENT_DOWNLOADS", 1),
            max_jobs=positive_int("MAX_JOBS", 16),
            max_inspections=positive_int("MAX_INSPECTIONS", 256),
            max_requests_per_minute=positive_int("RATE_LIMIT_PER_MINUTE", 12),
            inspection_ttl=positive_int("INSPECTION_TTL_SECONDS", 600),
            file_ttl=positive_int("FILE_TTL_SECONDS", 1800),
            inspection_timeout=positive_int("INSPECTION_TIMEOUT_SECONDS", 45),
            download_timeout=positive_int("DOWNLOAD_TIMEOUT_SECONDS", 600),
            secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
            public_url=os.getenv("PUBLIC_URL", "").rstrip("/"),
            cobalt_api_url=os.getenv("COBALT_API_URL", "http://127.0.0.1:9000/").strip(),
            cobalt_api_key=os.getenv("COBALT_API_KEY", "").strip(),
        )
