"""Safe read/update of the repo-root .env file for operator-managed keys."""
from __future__ import annotations

from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def update_env(values: dict[str, str]) -> None:
    """Upsert KEY=value lines in .env, preserving everything else."""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    if remaining:
        out.append("")
        out.append("# Updated via Power Up / Settings")
        for key, val in remaining.items():
            out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
