"""Build a source-code offer without environment files, credentials or media."""
import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT_FILES = {
    "README.md", "LICENSE", "NOTICE.md", "CHANGELOG.md", "DEPLOYMENT.md",
    "DEPLOY_RAILWAY.md", "DEPLOY_DOCKER.md", "GITHUB_SETUP.md", "VERIFICATION.md",
    "RENDER_UPDATE.md", "Dockerfile", "compose.yaml", "render.yaml", "railway.json",
    "run.py", "cobalt.lock.json", "requirements.txt", "requirements.lock.txt",
    "requirements-dev.txt", ".env.example", ".gitattributes", ".gitignore",
    ".dockerignore", "start.ps1", "start.sh",
}
SOURCE_DIRS = {"app", "static", "scripts", "tests", "docs"}
SOURCE_EXTENSIONS = {".py", ".js", ".cjs", ".css", ".html", ".svg", ".md"}


def make_bundle(project, output, cobalt_archive=None):
    project, output = Path(project).resolve(), Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for path in sorted(project.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                rel = path.relative_to(project)
                if any(part in {"__pycache__", ".git", ".venv", "node_modules", "data", ".pytest_cache"} for part in rel.parts):
                    continue
                # No hidden files or JSON/YAML runtime data from source trees.
                # Public manifests are explicitly allowlisted at the root.
                include = (len(rel.parts) == 1 and rel.name in ROOT_FILES) or (
                    rel.parts[0] in SOURCE_DIRS and path.suffix in SOURCE_EXTENSIONS
                    and not any(part.startswith(".") for part in rel.parts))
                if include:
                    archive.write(path, "StreamSave/" + rel.as_posix())
            if cobalt_archive and Path(cobalt_archive).is_file():
                archive.write(cobalt_archive, "upstream/cobalt-source.tar.gz")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cobalt-archive")
    args = parser.parse_args()
    make_bundle(args.project, args.output, args.cobalt_archive)
