#!/usr/bin/env bash
# Portable source-tree launcher. Does not install packages or modify hardware.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [[ -n "${PYTHON:-}" ]]; then
    python_bin="$PYTHON"
elif [[ -x "$project_dir/.venv/bin/python" ]]; then
    python_bin="$project_dir/.venv/bin/python"
else
    python_bin="python3"
fi
export PYTHONPATH="$project_dir${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_bin" -m sdr_research.lab_gui "$@"
