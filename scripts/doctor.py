"""Check local installation without downloading media."""
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

okay = sys.version_info >= (3, 12)
print(f"Python {sys.version.split()[0]}: {'OK' if okay else 'requires 3.12+'}")
for package in ("fastapi", "uvicorn", "python-dotenv", "httpx"):
    try:
        print(f"{package}: {importlib.metadata.version(package)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{package}: MISSING (install requirements.lock.txt)")
        okay = False
for command in ("ffmpeg", "ffprobe"):
    found = shutil.which(command)
    print(f"{command}: {'OK' if found else 'MISSING (install the actual FFmpeg programs)'}")
    okay = okay and bool(found)
source = os.getenv("COBALT_SOURCE_DIR", "").strip()
bundled = os.getenv("COBALT_BUNDLED", "true" if source else "false").lower() == "true"
if bundled:
    entry = Path(source) / "src/cobalt.js" if source else None
    present = entry is not None and entry.is_file()
    print(f"Cobalt source: {'OK' if present else 'MISSING (follow README.md)'}")
    okay = okay and present
    try:
        version = subprocess.check_output(["node", "--version"], text=True, timeout=5).strip()
        valid = int(version.lstrip("v").split(".")[0]) >= 24
        print(f"Node: {version}{'' if valid else ' (requires Node 24+)'}")
        okay = okay and valid
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Node: MISSING (install Node 24+)")
        okay = False
else:
    print("Cobalt API: python run.py will check the configured instance at startup.")
print("YouTube access is tested separately by submitting a link in the dashboard.")
sys.exit(0 if okay else 1)
