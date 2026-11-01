"""Package source only; never include credentials, virtualenvs, workspaces or logs."""

from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent.parent
destination = root / "dist" / "internal-harness-v2.zip"
destination.parent.mkdir(exist_ok=True)
files = [root / "README.md", root / "pyproject.toml", root / ".gitignore",
         root / "docs" / "benchmark-result.json"]
for directory, pattern in (("internal_harness", "*.py"), ("tests", "*.py"),
                           ("scripts", "*.py"), ("docs", "*.md"),
                           ("examples", "*.json"), ("config", "*.example.json")):
    files.extend(sorted((root / directory).glob(pattern)))
with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, "harness_v2/" + path.relative_to(root).as_posix())
print(destination)
print(f"{len(files)} source/config/documentation files; no environment or runtime data")
