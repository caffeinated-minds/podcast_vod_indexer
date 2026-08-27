#!/usr/bin/env python3
import sys
from pathlib import Path


ALLOWED_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".png",
    ".svg",
    ".txt",
    ".webp",
    ".woff",
    ".woff2",
}

FORBIDDEN_SUFFIXES = {
    ".db",
    ".env",
    ".key",
    ".log",
    ".sqlite",
    ".sqlite3",
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else "output")

    if not root.exists():
        print(f"Public artifact directory does not exist: {root}")
        return 1

    if not root.is_dir():
        print(f"Public artifact path is not a directory: {root}")
        return 1

    index_path = root / "index.html"
    if not index_path.is_file():
        print(f"Missing required public entrypoint: {index_path}")
        return 1

    files = [path for path in root.rglob("*") if path.is_file()]
    if not files:
        print(f"No public artifact files found in {root}")
        return 1

    errors = []
    for path in files:
        relative_path = path.relative_to(root)
        suffix = path.suffix.lower()

        if any(part.startswith(".") for part in relative_path.parts):
            errors.append(f"hidden file is not allowed: {relative_path}")
        elif suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden file type: {relative_path}")
        elif suffix not in ALLOWED_SUFFIXES:
            errors.append(f"unexpected file type: {relative_path}")

    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Validated {len(files)} public artifact file(s) in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
