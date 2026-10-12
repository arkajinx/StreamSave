"""Bounded, single-process download jobs and expiring per-browser metadata."""

import logging
import math
import re
import secrets
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .cobalt import CobaltClient
from .media import MediaError, canonical_url, format_options, inspect_video, number, probe_media

logger = logging.getLogger(__name__)
TERMINAL = {"ready", "failed", "cancelled"}


def tree_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


def download_media(url, choice, folder, max_bytes, timeout, cancel, progress, guard, *, settings=None) -> Path:
    settings = settings or Settings.from_env()
    url = canonical_url(url)
    started = time.monotonic()
    partial = CobaltClient(settings).download(url, choice, folder, max_bytes, timeout, cancel, progress, guard)
    try:
        if cancel.is_set():
            raise MediaError("Download cancelled.", 409)
        progress("stage:Checking the completed file")
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise MediaError("This download took too long. Try a smaller output.", 504)
        probe_media(partial, choice, settings.max_duration, timeout=min(15, remaining))
        guard()
        if cancel.is_set():
            raise MediaError("Download cancelled.", 409)
        path = folder / ("media." + choice["container"])
        partial.replace(path)
        return path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


@dataclass
class Inspection:
    owner: str
    url: str
    info: dict
    choices: list[dict]
    created: float = field(default_factory=time.monotonic)


@dataclass
class Job:
    id: str
    owner: str
    url: str
    title: str
    choice: dict
    status: str = "queued"
    stage: str = "Waiting for an available slot"
    progress: float = 0
    speed: float = 0
    eta: int | None = None
    error: str | None = None
    path: Path | None = None
    size: int = 0
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    readers: int = 0


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.inspections: dict[str, Inspection] = {}
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pending = deque()
        self.condition = threading.Condition(self.lock)
        self.workers = []
        self.inspect_slots = threading.BoundedSemaphore(settings.max_concurrent)
        self.rates: dict[str, list[float]] = {}
        self.cleaner = None

    def start(self):
        root = self.settings.download_dir
        root.mkdir(parents=True, exist_ok=True)
        # Jobs are memory-only: remove only our recognisable, abandoned job directories.
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink() and re.fullmatch(r"[a-f0-9]{32}", child.name):
                shutil.rmtree(child, ignore_errors=True)
        self.cleaner = threading.Thread(target=self._cleanup_loop, daemon=True, name="temporary-file-cleanup")
        self.cleaner.start()
        for index in range(self.settings.max_concurrent):
            worker = threading.Thread(target=self._worker, daemon=True, name=f"download-{index}")
            self.workers.append(worker)
            worker.start()

    def close(self):
        with self.condition:
            self.stop.set()
            for job in self.jobs.values():
                if job.status not in TERMINAL:
                    job.cancel.set()
            for job in self.pending:
                self._update(job, status="cancelled", stage="Cancelled", finished=time.monotonic())
            self.pending.clear()
            self.condition.notify_all()
        for worker in self.workers:
            worker.join(timeout=8)
        if self.cleaner:
            self.cleaner.join(timeout=2)

    def _worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stop.is_set() or bool(self.pending))
                if self.stop.is_set():
                    return
                job = self.pending.popleft()
                job.status = "downloading"
                job.stage = "Connecting to YouTube"
            self._run(job)

    def _cleanup_loop(self):
        while not self.stop.wait(15):
            try:
                self.cleanup()
            except OSError:
                logger.exception("Temporary-file cleanup failed")

    def cleanup(self):
        now = time.monotonic()
        with self.lock:
            for key, item in list(self.inspections.items()):
                if now - item.created > self.settings.inspection_ttl:
                    self.inspections.pop(key, None)
            for key, job in list(self.jobs.items()):
                if job.finished is not None and now - job.finished > self.settings.file_ttl and job.readers == 0:
                    shutil.rmtree(self.settings.download_dir / key, ignore_errors=True)
                    self.jobs.pop(key, None)
            for key, hits in list(self.rates.items()):
                if not hits or now - hits[-1] > 60:
                    self.rates.pop(key, None)

    def rate_limit(self, client: str):
        now = time.monotonic()
        with self.lock:
            hits = [x for x in self.rates.get(client, []) if now - x < 60]
            if len(hits) >= self.settings.max_requests_per_minute:
                raise MediaError("Too many requests. Wait a minute before trying again.", 429)
            if client not in self.rates and len(self.rates) >= 4096:
                raise MediaError("The server is busy. Please try again shortly.", 429)
            self.rates[client] = hits + [now]

    def inspect(self, owner: str, raw_url: str) -> dict:
        url = canonical_url(raw_url)
        self.cleanup()
        with self.lock:
            if len(self.inspections) >= self.settings.max_inspections:
                raise MediaError("The server is busy. Please try again in a few minutes.", 503)
        if not self.inspect_slots.acquire(blocking=False):
            raise MediaError("The server is checking other links. Please try again shortly.", 429)
        try:
            info = inspect_video(url, self.settings.inspection_timeout, settings=self.settings)
        finally:
            self.inspect_slots.release()
        duration = number(info.get("duration"))
        if duration > self.settings.max_duration:
            raise MediaError(f"This server supports videos up to {math.ceil(self.settings.max_duration / 60)} minutes.")
        choices = [x for x in format_options(info) if not x.get("estimated_bytes") or x["estimated_bytes"] <= self.settings.max_file_bytes]
        if not choices:
            raise MediaError("No supported video/audio format fits this server's size limit.")
        token = secrets.token_hex(16)
        # Retain only the needed metadata; do not cache media URLs or huge provider responses.
        kept = {key: info.get(key) for key in ["id", "title", "duration", "uploader", "channel"]}
        with self.lock:
            if len(self.inspections) >= self.settings.max_inspections:
                raise MediaError("The server is busy. Please try again shortly.", 503)
            self.inspections[token] = Inspection(owner, url, kept, choices)
        return {"inspection_id": token, "title": str(info.get("title") or "YouTube video")[:500],
                "channel": str(info.get("uploader") or info.get("channel") or "")[:250], "duration": duration or None,
                "thumbnail": f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg", "url": url,
                "options": [{k: v for k, v in x.items() if k not in {"selector", "cobalt"}} for x in choices],
                "options_are_presets": True,
                "expires_in": self.settings.inspection_ttl}

    def submit(self, owner: str, inspection_id: str, option_id: str, authorized: bool) -> dict:
        if not authorized:
            raise MediaError("Confirm that you have authorization to download this media.")
        with self.lock:
            item = self.inspections.get(inspection_id)
            if item is None or item.owner != owner:
                raise MediaError("This preview was not found. Check the video link again.", 404)
            if time.monotonic() - item.created > self.settings.inspection_ttl:
                raise MediaError("This preview expired. Check the video link again.", 410)
            choice = next((x for x in item.choices if x["id"] == option_id), None)
            if not choice:
                raise MediaError("Select one of the available output formats.")
            self.cleanup()
            # Retain terminal snapshots while possible; recycle records with no
            # downloadable file when a new job needs space. Memory stays bounded.
            discardable = sorted((j for j in self.jobs.values() if j.status in {"failed", "cancelled"} and j.readers == 0),
                                 key=lambda j: j.finished or j.created)
            while len(self.jobs) >= self.settings.max_jobs and discardable:
                self.jobs.pop(discardable.pop(0).id, None)
            if len(self.jobs) >= self.settings.max_jobs:
                raise MediaError("The download queue is full. Please try again later.", 429)
            if sum(j.owner == owner and j.status not in TERMINAL for j in self.jobs.values()) >= 2:
                raise MediaError("You already have two active downloads. Wait for one to finish.", 429)
            self.storage_guard()
            job = Job(secrets.token_hex(16), owner, item.url, str(item.info.get("title") or "video"), choice.copy())
            self.jobs[job.id] = job
            self.pending.append(job)
            self.condition.notify()
            return self._snapshot(job)

    def storage_guard(self, folder: Path | None = None):
        root = self.settings.download_dir
        if folder and tree_size(folder) > self.settings.max_file_bytes * 2 + 16 * 1024 * 1024:
            raise MediaError("This job exceeded the temporary size limit. Choose a smaller output.")
        if tree_size(root) > self.settings.max_storage_bytes or shutil.disk_usage(root).free < self.settings.min_free_bytes:
            raise MediaError("The server has insufficient temporary storage. Please try again later.", 503)

    def _update(self, job: Job, **values):
        with self.lock:
            for key, value in values.items():
                setattr(job, key, value)

    def _run(self, job: Job):
        folder = self.settings.download_dir / job.id
        fractions = {}
        components = 1
        last_guard = [0.0]

        def progress(line: str):
            if line.startswith("progress:"):
                pieces = line[len("progress:"):].split("|")
                if len(pieces) < 5:
                    return
                downloaded, total, estimate, speed, eta = [number(x) for x in pieces[:5]]
                stream_id = pieces[5] if len(pieces) > 5 else "media"
                divisor = total or estimate
                if divisor:
                    fractions[stream_id] = min(1.0, downloaded / divisor)
                percent = min(90, 90 * sum(fractions.values()) / components)
                self._update(job, progress=max(job.progress, round(percent, 1)), speed=speed,
                             eta=round(eta) if eta else None, stage="Downloading media")
            elif line.startswith("stage:"):
                self._update(job, stage=line.removeprefix("stage:"), speed=0, eta=None)

        def guard():
            if time.monotonic() - last_guard[0] > 0.25:
                self.storage_guard(folder)
                last_guard[0] = time.monotonic()

        try:
            if job.cancel.is_set():
                raise MediaError("Download cancelled.", 409)
            folder.mkdir(mode=0o700)
            self._update(job, status="downloading", stage="Connecting to YouTube")
            path = download_media(job.url, job.choice, folder, self.settings.max_file_bytes,
                                  self.settings.download_timeout, job.cancel, progress, guard, settings=self.settings)
            self.storage_guard(folder)
            if job.cancel.is_set():
                raise MediaError("Download cancelled.", 409)
            size = path.stat().st_size
            self._update(job, path=path, size=size, status="ready", stage="Ready to save", progress=100,
                         speed=0, eta=None, finished=time.monotonic())
        except Exception as exc:
            cancelled = job.cancel.is_set()
            message = str(exc) if isinstance(exc, MediaError) else "The server could not finish this download. Try again later."
            if not isinstance(exc, MediaError):
                logger.exception("Download job failed")
            shutil.rmtree(folder, ignore_errors=True)
            self._update(job, status="cancelled" if cancelled else "failed", stage="Cancelled" if cancelled else "Download failed",
                         error=None if cancelled else message, speed=0, eta=None, finished=time.monotonic())

    def _owned_job(self, owner: str, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None or job.owner != owner:
            raise MediaError("This download expired or was not found in this browser.", 404)
        if job.finished is not None and time.monotonic() - job.finished > self.settings.file_ttl:
            raise MediaError("This temporary download expired. Check the link and create a new download.", 410)
        return job

    def _snapshot(self, job: Job) -> dict:
        seconds = max(0, round(self.settings.file_ttl - (time.monotonic() - job.finished))) if job.finished else None
        return {"id": job.id, "title": job.title[:500], "status": job.status, "stage": job.stage,
                "progress": job.progress, "speed": job.speed, "eta": job.eta, "error": job.error,
                "size": job.size, "container": job.choice["container"], "expires_in": seconds,
                "file_url": f"/api/jobs/{job.id}/file" if job.status == "ready" else None}

    def status(self, owner: str, job_id: str) -> dict:
        with self.lock:
            return self._snapshot(self._owned_job(owner, job_id))

    def cancel_job(self, owner: str, job_id: str) -> dict:
        with self.lock:
            job = self._owned_job(owner, job_id)
            if job.readers:
                raise MediaError("The file is currently being saved. Wait for it to finish.", 409)
            job.cancel.set()
            if job.status in TERMINAL:
                shutil.rmtree(self.settings.download_dir / job_id, ignore_errors=True)
                job.path = None
                job.status = "cancelled"
                job.stage = "Cancelled"
                job.finished = time.monotonic()
            elif job.status == "queued":
                # Removing the queue entry also bounds cancelled work; it does
                # not wait behind a busy worker or leave cancelled futures queued.
                self.pending.remove(job)
                job.status = "cancelled"
                job.stage = "Cancelled"
                job.finished = time.monotonic()
            else:
                job.status = "cancelling"
                job.stage = "Cancelling download"
            return self._snapshot(job)

    def claim_file(self, owner: str, job_id: str) -> tuple[Path, str]:
        with self.lock:
            job = self._owned_job(owner, job_id)
            if job.status != "ready" or job.path is None or not job.path.is_file():
                raise MediaError("The file is not ready. Wait for processing to finish.", 409)
            job.readers += 1
            title = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", job.title).strip(" .")[:100] or "video"
            return job.path, title + "." + job.choice["container"]

    def release_file(self, job_id: str):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].readers = max(0, self.jobs[job_id].readers - 1)
