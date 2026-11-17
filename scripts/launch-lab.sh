#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/launcher-common.sh"
launch_viewer sdr_research.lab_gui "$@"
