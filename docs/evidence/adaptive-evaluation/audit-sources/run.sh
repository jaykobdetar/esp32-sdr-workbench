#!/usr/bin/env bash
# Offline host tests only. No serial access, firmware installation or RF.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../.." && pwd)
OUT=$(mktemp -d "${TMPDIR:-/tmp}/sdr-source-audit.XXXXXX")
echo "Host audit output: $OUT"
python3 "$HERE/build_integrated.py" --root "$ROOT" --output "$OUT"
# The original environment could not run LeakSanitizer under ptrace. Keeping this
# explicit reproduces ASan/UBSan coverage, NOT a successful leak-sanitizer check.
export ASAN_OPTIONS=detect_leaks=0
for opt in 0 2; do
  cc -std=c11 -O"$opt" -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -I"$ROOT" "$HERE/properties.c" -o "$OUT/properties-O$opt"
  "$OUT/properties-O$opt" | tee "$OUT/properties-O$opt.log"
  grep -q 'mismatch streams=0/4096' "$OUT/properties-O$opt.log"
  cc -std=c11 -O"$opt" -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -I"$OUT" "$OUT/integrated.c" -o "$OUT/integrated-O$opt"
  "$OUT/integrated-O$opt" | tee "$OUT/integrated-O$opt.log"
done
cc -std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -I"$ROOT" "$HERE/crop_sensitivity.c" -o "$OUT/crop_sensitivity"
"$OUT/crop_sensitivity" | tee "$OUT/crop_sensitivity.log"
