import tempfile
import unittest
import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_public_artifacts.py"
)
SPEC = importlib.util.spec_from_file_location(
    "validate_public_artifacts",
    SCRIPT_PATH,
)
assert SPEC is not None
validate_public_artifacts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validate_public_artifacts)


class PublicArtifactValidationTests(unittest.TestCase):
    def test_accepts_html_and_csv_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "index.html").write_text("<html></html>")
            (output_dir / "matches.csv").write_text("title,url\n")

            self.assertEqual(
                validate_public_artifacts.main([str(output_dir)]),
                0,
            )

    def test_rejects_sqlite_database_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "index.html").write_text("<html></html>")
            (output_dir / "index.db").write_text("private")

            self.assertEqual(
                validate_public_artifacts.main([str(output_dir)]),
                1,
            )

    def test_requires_index_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "matches.csv").write_text("title,url\n")

            self.assertEqual(
                validate_public_artifacts.main([str(output_dir)]),
                1,
            )
