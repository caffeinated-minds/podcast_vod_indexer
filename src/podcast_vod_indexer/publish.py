from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess

from podcast_vod_indexer.artifacts import validate_public_artifacts


DEFAULT_COMMIT_MESSAGE = "Update generated public index"


class PublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    changed: bool
    committed: bool
    pushed: bool
    commit_sha: str | None = None


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def publish_public_artifacts(
    output_dir: Path | str = Path("output"),
    *,
    branch: str = "master",
    remote: str = "origin",
    commit_message: str = DEFAULT_COMMIT_MESSAGE,
    run_command: RunCommand | None = None,
) -> PublishResult:
    output_dir = Path(output_dir)
    run_command = run_command or subprocess.run

    validate_public_artifacts(output_dir)
    _require_branch(branch, run_command)
    _require_remote(remote, run_command)
    _require_path_ignored("data/index.db", run_command)
    _require_no_unexpected_dirty_files(output_dir, run_command)

    _git(["add", "--", output_dir.as_posix()], run_command)

    if not _has_staged_changes(output_dir, run_command):
        return PublishResult(changed=False, committed=False, pushed=False)

    _git(["commit", "-m", commit_message], run_command)
    commit_sha = _git(
        ["rev-parse", "--short", "HEAD"],
        run_command,
    ).stdout.strip()
    _git(["push", remote, branch], run_command)

    return PublishResult(
        changed=True,
        committed=True,
        pushed=True,
        commit_sha=commit_sha,
    )


def _git(
    args: list[str | Path],
    run_command: RunCommand,
) -> subprocess.CompletedProcess[str]:
    completed = run_command(
        ["git", *[str(arg) for arg in args]],
        check=False,
        text=True,
        capture_output=True,
    )

    if completed.returncode != 0:
        command = "git " + " ".join(str(arg) for arg in args)
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PublishError(f"{command} failed: {detail}")

    return completed


def _require_branch(branch: str, run_command: RunCommand) -> None:
    current_branch = _git(
        ["branch", "--show-current"],
        run_command,
    ).stdout.strip()

    if current_branch != branch:
        raise PublishError(
            f"Refusing to publish from branch '{current_branch}'. "
            f"Expected '{branch}'."
        )


def _require_remote(remote: str, run_command: RunCommand) -> None:
    _git(["remote", "get-url", remote], run_command)


def _require_path_ignored(path: str, run_command: RunCommand) -> None:
    completed = run_command(
        ["git", "check-ignore", "-q", path],
        check=False,
        text=True,
        capture_output=True,
    )

    if completed.returncode != 0:
        raise PublishError(f"Refusing to publish because {path} is not ignored")


def _require_no_unexpected_dirty_files(
    output_dir: Path,
    run_command: RunCommand,
) -> None:
    completed = _git(
        ["status", "--porcelain=v1", "--untracked-files=all"],
        run_command,
    )
    output_prefix = output_dir.as_posix().rstrip("/") + "/"
    output_name = output_dir.as_posix().rstrip("/")

    unexpected_paths = []
    for line in completed.stdout.splitlines():
        paths = _status_paths(line)
        if not paths:
            continue

        for path in paths:
            if path == output_name or path.startswith(output_prefix):
                continue

            unexpected_paths.append(path)

    if unexpected_paths:
        formatted_paths = "\n".join(f"- {path}" for path in unexpected_paths)
        raise PublishError(
            "Refusing to publish with non-output working tree changes:\n"
            f"{formatted_paths}"
        )


def _status_paths(line: str) -> list[str]:
    if len(line) < 4:
        return []

    path_text = line[3:]

    if " -> " in path_text:
        return path_text.split(" -> ")

    return [path_text]


def _has_staged_changes(
    output_dir: Path,
    run_command: RunCommand,
) -> bool:
    completed = run_command(
        ["git", "diff", "--cached", "--quiet", "--", output_dir.as_posix()],
        check=False,
        text=True,
        capture_output=True,
    )

    if completed.returncode == 0:
        return False

    if completed.returncode == 1:
        return True

    detail = completed.stderr.strip() or completed.stdout.strip()
    raise PublishError(f"git diff --cached failed: {detail}")
