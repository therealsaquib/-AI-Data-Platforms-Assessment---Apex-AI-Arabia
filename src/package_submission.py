"""Create the named assessment ZIP without local databases or runtime artifacts."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "Mohd_Saqib_Shaikh_JuniorDataEngineer_48H_Assessment.zip"
INCLUDED_PATHS = (
    "src",
    "data/raw",
    "data/reference.json",
    "sql",
    "tests",
    "docs",
    "README.md",
    "requirements.txt",
    "config.yaml",
    "Makefile",
)
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "logs"}


def create_package() -> Path:
    package_path = ROOT / PACKAGE_NAME
    with ZipFile(package_path, "w", compression=ZIP_DEFLATED) as archive:
        for relative in INCLUDED_PATHS:
            path = ROOT / relative
            candidates = [path] if path.is_file() else sorted(path.rglob("*"))
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                if EXCLUDED_PARTS.intersection(candidate.parts) or candidate.suffix.lower() == ".db":
                    continue
                archive.write(candidate, candidate.relative_to(ROOT))
    return package_path


if __name__ == "__main__":
    print(create_package())
