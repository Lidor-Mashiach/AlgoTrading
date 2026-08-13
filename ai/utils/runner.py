"""
Shared step runner.

Every folder runner (and the top-level pipeline runner) declares a list of steps as
(relative_script_path, description) tuples and hands it to run_steps. Each step runs in
its own subprocess, so the steps stay isolated and a failure stops the run. To skip a
step, comment out its tuple in the list. Each step and the whole run are timed.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import time


def _format_duration(seconds: float) -> str:
    """Human-readable duration, for example '3m 12s' or '45.7s'."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs}s"


def run_steps(base_dir: pathlib.Path, steps: list[tuple[str, str]]) -> None:
    """
    Run each step script in order, relative to base_dir. Raises if any step fails so the
    pipeline does not continue on a broken stage. Times each step and the whole run.
    """
    base_dir = pathlib.Path(base_dir)
    total = len(steps)
    durations: list[float] = []
    run_start = time.perf_counter()

    for index, (relative_script, description) in enumerate(steps, start=1):
        script_path = base_dir / relative_script
        print("\n" + "=" * 78)
        print(f"[step {index}/{total}] {relative_script}")
        print(f"           {description}")
        print("=" * 78)

        if not script_path.exists():
            raise FileNotFoundError(f"Step script not found: {script_path}")

        step_start = time.perf_counter()
        subprocess.run([sys.executable, str(script_path)], check=True)
        elapsed = time.perf_counter() - step_start
        durations.append(elapsed)
        print(f"[step {index}/{total}] done in {_format_duration(elapsed)}")

    total_elapsed = time.perf_counter() - run_start
    print("\n" + "-" * 78)
    print(f"completed {total} step(s) in {_format_duration(total_elapsed)}")
    for index, ((relative_script, _), elapsed) in enumerate(zip(steps, durations), start=1):
        print(f"  step {index}: {_format_duration(elapsed):>8}  {relative_script}")
    print("-" * 78)