"""Build a source release ZIP while excluding local data and credentials."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    ".pnpm-store",
    ".mypy_cache",
    ".tox",
    ".nox",
    "htmlcov",
    "private_keys",
    "secrets",
}
UNSAFE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".dump",
    ".backup",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".tmp",
}


def is_excluded(relative: Path) -> bool:
    folded_parts = {part.casefold() for part in relative.parts}
    name = relative.name.casefold()
    return bool(
        folded_parts & EXCLUDED_PARTS
        or name == ".env"
        or name.startswith(".env.")
        or name.startswith("~$")
        or name.endswith(".tsbuildinfo")
        or name in {".coverage", "coverage.xml", ".eslintcache"}
        or relative.suffix.casefold() in UNSAFE_SUFFIXES
        or name.endswith((".docx~", ".pdf~"))
    )


def build(output: Path) -> tuple[int, list[str]]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or path.resolve() == output:
                continue
            relative = path.relative_to(ROOT)
            if is_excluded(relative):
                continue
            archive.write(path, relative.as_posix())
            included.append(relative.as_posix())
    unsafe = [name for name in included if is_excluded(Path(name))]
    if unsafe:
        raise RuntimeError("Release ZIP contains excluded files: " + ", ".join(unsafe))
    return len(included), included


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT.parent / "AssetCore-release.zip",
    )
    args = parser.parse_args()
    count, _ = build(args.output)
    print(f"Release ZIP: {args.output.resolve()} ({count} files)")


if __name__ == "__main__":
    main()
