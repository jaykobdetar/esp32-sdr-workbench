# SPEC command argument validation

The shared snapshot-spectrum handler now parses the complete argument list with
`burst_parse_uints` before initializing the FFT or invoking acquisition. Previously,
`sscanf` treated a malformed seventh (optional stats) field as if it were absent.
For example, `SPEC 0 1 1 0 6 256 garbage` could start an unlimited snapshot stream
on a target supporting rate code 6 instead of returning `ERR spec_args`.

The command accepts six or seven space-separated unsigned decimal arguments:
`SPEC duration_ms stride units detector rate fft_size [stats]`. Existing numeric
range checks remain unchanged. Omitted stats defaults to zero; explicit stats
zero and one remain valid. Explicit duration zero still requests unlimited
operation, terminated by a stop request or an existing failure condition. Signed
values, decimal overflow, malformed tokens, and excess fields are rejected before
receiver activity. Repeated/trailing spaces and leading decimal zeroes are valid.
The parser follows the existing serial helper's space-separated syntax, rather
than the broader whitespace syntax accepted by `sscanf`.

## Host regression coverage

Run `python -m pytest firmware/tests/test_spectrum_arguments.py -q`.

The tests compile the actual `firmware/main/common/spectrum.c`, with SDK and
transport stubs, at `-O0`, `-O2`, and `-O2 -fsanitize=undefined` (no sanitizer
recovery). Invalid-command tests assert the exact error response and zero FFT
initializations, acquisitions, stop polls, and telemetry initializations. Coverage
includes each numeric position, missing and excess fields, signs, suffixes,
overflow, range boundaries, and the original malformed optional-stats case with
both finite and unlimited durations.

Valid commands cover optional stats, duration boundaries, supported FFT sizes,
rate codes, and acquisition failure, FFT initialization failure, failed initial
response, and explicit stop. Additional host compilations and command tests cover
the S2, S3, C2, C3, C6, C61, and H2 preprocessor branches under UBSan. The original
source was also compiled with the harness and failed the malformed unlimited
command regression as expected.

These are command-boundary host tests, not real ESP-IDF builds, hardware tests,
transport timing tests, or successful RF/FFT acquisition validation. No firmware
was flashed and no RF operation was performed.


## Serial framing follow-up

The shared serial line reader also rejects an entire line containing an embedded
NUL byte. Without this boundary check, a C-string parser could see a valid prefix
and never see the malformed suffix. The existing invalid-line response is
`ERR command_length`; no command handler is called, and the next complete valid
line remains usable. Raw-byte UART tests link the production serial and spectrum
code at `-O0` and `-O2` under UBSan, covering NUL before optional/extra tokens,
a leading NUL, ordinary trailing garbage, and subsequent valid CRLF input.
