from dataclasses import dataclass
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


@dataclass(frozen=True)
class PublicArtifactValidationResult:
    root: Path
    file_count: int


class PublicArtifactValidationError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def validate_public_artifacts(
    root: Path | str = Path("output"),
) -> PublicArtifactValidationResult:
    root = Path(root)

    errors = []

    if not root.exists():
        raise PublicArtifactValidationError(
            [f"Public artifact directory does not exist: {root}"]
        )

    if not root.is_dir():
        raise PublicArtifactValidationError(
            [f"Public artifact path is not a directory: {root}"]
        )

    index_path = root / "index.html"
    if not index_path.is_file():
        errors.append(f"Missing required public entrypoint: {index_path}")

    files = [path for path in root.rglob("*") if path.is_file()]
    if not files:
        errors.append(f"No public artifact files found in {root}")

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
        raise PublicArtifactValidationError(errors)

    return PublicArtifactValidationResult(
        root=root,
        file_count=len(files),
    )
