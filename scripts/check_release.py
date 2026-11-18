#!/usr/bin/env python3
"""Build, validate, and install the wheel into a temporary clean environment."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def run(*command: str, cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    run(python, "-m", "ruff", "check", ".", cwd=root)
    run(python, "-m", "pytest", "-q", cwd=root)
    run(python, "-m", "compileall", "-q", "src", "tests", cwd=root)
    run(python, "-m", "build", "--no-isolation", cwd=root)
    run(python, "-m", "twine", "check", *map(str, (root / "dist").glob("*")), cwd=root)

    wheel = next((root / "dist").glob("*.whl"))
    with tempfile.TemporaryDirectory(prefix="voicebridge-release-") as directory:
        environment = Path(directory) / "venv"
        run(python, "-m", "venv", str(environment))
        if sys.platform == "win32":
            target_python = environment / "Scripts" / "python.exe"
            target_cli = environment / "Scripts" / "voicebridge.exe"
        else:
            target_python = environment / "bin" / "python"
            target_cli = environment / "bin" / "voicebridge"
        run(str(target_python), "-m", "pip", "install", "--no-deps", str(wheel))
        run(str(target_cli), "--version")
    print("Release check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
