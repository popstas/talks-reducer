"""Regenerate CHANGELOG.md with git-cliff.

Runs as a bump-my-version pre-commit hook, where ``BVHOOK_NEW_VERSION_TAG``
names the tag that does not exist yet, so the new release gets its own
section instead of landing under "Unreleased". Run it by hand without the
variable to refresh the file from the existing tags.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = "CHANGELOG.md"


def find_git_cliff() -> str:
    """Return the git-cliff executable, preferring the one beside this Python.

    The hook may run with an interpreter whose ``Scripts``/``bin`` folder is
    not on ``PATH`` (an unactivated ``.venv``), so look there first.
    """
    name = "git-cliff.exe" if os.name == "nt" else "git-cliff"
    for folder in (
        Path(sys.executable).parent,
        ROOT / ".venv" / "Scripts",
        ROOT / ".venv" / "bin",
    ):
        candidate = folder / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("git-cliff")
    if found:
        return found
    sys.exit("git-cliff not found; install it with: pip install git-cliff")


def main() -> None:
    """Write CHANGELOG.md and stage it so the version-bump commit includes it."""
    command = [find_git_cliff(), "--config", "cliff.toml", "--output", CHANGELOG]
    tag = os.environ.get("BVHOOK_NEW_VERSION_TAG")
    if tag:
        command += ["--tag", tag]
    subprocess.run(command, check=True, cwd=ROOT)
    subprocess.run(["git", "add", CHANGELOG], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
