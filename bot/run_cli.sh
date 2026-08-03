#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="${PWD}/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m cli "$@"
