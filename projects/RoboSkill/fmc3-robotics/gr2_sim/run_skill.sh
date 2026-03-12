#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${CONDA_PREFIX:-}" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda is not available in the current shell. Activate env_isaaclab first." >&2
    exit 1
  fi
  eval "$(conda shell.bash hook)"
  conda activate "${CONDA_ENV_NAME:-env_isaaclab}"
fi

export PYTHONUNBUFFERED=1

cd "${SCRIPT_DIR}"
python skill.py "$@"
