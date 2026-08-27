from pathlib import Path
import subprocess
import tempfile
import unittest

from podcast_vod_indexer.publish import (
    PublishError,
    publish_public_artifacts,
)


class FakeGit:
    def __init__(
        self,
        *,
        branch: str = "master",
        status: str = "",
        staged_changes: bool = True,
    ) -> None:
        self.branch = branch
        self.status = status
        self.staged_changes = staged_changes
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)

        if command == ["git", "branch", "--show-current"]:
            return self._completed(stdout=f"{self.branch}\n")

        if command == ["git", "remote", "get-url", "origin"]:
            return self._completed(stdout="git@example.com:repo.git\n")

        if command == ["git", "check-ignore", "-q", "data/index.db"]:
            return self._completed()

        if command == [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]:
            return self._completed(stdout=self.status)

        if command[:3] == ["git", "add", "--"]:
            return self._completed()

        if command[:5] == ["git", "diff", "--cached", "--quiet", "--"]:
            return self._completed(
                returncode=1 if self.staged_changes else 0
            )

        if command[:3] == ["git", "commit", "-m"]:
            return self._completed()

        if command == ["git", "rev-parse", "--short", "HEAD"]:
            return self._completed(stdout="abc1234\n")

        if command == ["git", "push", "origin", "master"]:
            return self._completed()

        return self._completed(returncode=1, stderr="unexpected command")

    def _completed(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )


class PublishPublicArtifactsTests(unittest.TestCase):
    def test_commits_and_pushes_changed_output_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()
            (output_dir / "index.html").write_text("<html></html>")
            fake_git = FakeGit(
                status=f" M {output_dir.as_posix()}/index.html\n"
            )

            result = publish_public_artifacts(
                output_dir,
                run_command=fake_git,
            )

        self.assertTrue(result.changed)
        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertEqual(result.commit_sha, "abc1234")
        self.assertIn(
            ["git", "add", "--", output_dir.as_posix()],
            fake_git.commands,
        )
        self.assertNotIn(["git", "add", "-A"], fake_git.commands)

    def test_refuses_non_output_working_tree_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()
            (output_dir / "index.html").write_text("<html></html>")
            fake_git = FakeGit(
                status=(
                    f" M {output_dir.as_posix()}/index.html\n"
                    " M README.md\n"
                )
            )

            with self.assertRaises(PublishError):
                publish_public_artifacts(output_dir, run_command=fake_git)

        self.assertNotIn(
            ["git", "add", "--", output_dir.as_posix()],
            fake_git.commands,
        )

    def test_skips_commit_when_output_has_no_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()
            (output_dir / "index.html").write_text("<html></html>")
            fake_git = FakeGit(staged_changes=False)

            result = publish_public_artifacts(
                output_dir,
                run_command=fake_git,
            )

        self.assertFalse(result.changed)
        self.assertFalse(result.committed)
        self.assertFalse(result.pushed)
        self.assertNotIn(
            ["git", "commit", "-m", "Update generated public index"],
            fake_git.commands,
        )

    def test_refuses_non_master_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()
            (output_dir / "index.html").write_text("<html></html>")
            fake_git = FakeGit(branch="feature")

            with self.assertRaises(PublishError):
                publish_public_artifacts(output_dir, run_command=fake_git)
