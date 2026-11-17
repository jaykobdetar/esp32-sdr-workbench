#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SDK=/home/jaykob/Documents/Codex/2026-11-10/i-ha/work/esp-idf
export IDF_PATH="$SDK" IDF_TOOLS_PATH=/home/jaykob/Documents/Codex/2026-11-10/i-ha/work/idf-tools
export IDF_COMPONENT_MANAGER=0
source "$SDK/export.sh"
for mode in OFF ON; do
 b="$ROOT/research-output/build-$mode"
 cmake -S "$ROOT/firmware" -B "$b" -G Ninja -DIDF_TARGET=esp32 -DPAUSED_PACKET_EXTRACT="$mode" -DSDKCONFIG="$b/sdkconfig" -DSDKCONFIG_DEFAULTS="$ROOT/firmware/sdkconfig.defaults.esp32" -DPYTHON="$IDF_PYTHON_ENV_PATH/bin/python"
 cmake --build "$b" -- -j2
 done
