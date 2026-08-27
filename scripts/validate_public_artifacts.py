#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from podcast_vod_indexer.artifacts import (  # noqa: E402
    PublicArtifactValidationError,
    validate_public_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else "output")

    try:
        result = validate_public_artifacts(root)
    except PublicArtifactValidationError as validation_error:
        for error in validation_error.errors:
            print(error)
        return 1

    print(
        f"Validated {result.file_count} public artifact file(s) "
        f"in {result.root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
