#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

python -m pip install --upgrade twine

if [[ ! -d dist ]]; then
  "${PROJECT_ROOT}/scripts/build-dist.sh"
fi

if [[ -n "${TWINE_REPOSITORY_URL:-}" ]]; then
  twine upload --repository-url "${TWINE_REPOSITORY_URL}" dist/*
else
  twine upload dist/*
fi
