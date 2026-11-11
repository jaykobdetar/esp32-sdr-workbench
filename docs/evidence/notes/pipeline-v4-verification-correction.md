# Pipeline v4 fused verification metadata correction

`firmware-pipeline/artifacts-pipeline-v4fused/BUILD_VERIFICATION.json` records
`aperture_start` as `0x3ffe0000`. That field is a metadata typo. The correct
reserved and accessed capture aperture is `[0x3ffe8000, 0x3fff8000)`.

Evidence from the reviewed image and source:
- `main/targets/esp32/receiver.c`: SOC_RESERVE_MEMORY_REGION starts at0x3ffe8000;
  the constant `samples` pointer is0x3ffe8000.
- `main/targets/esp32/sram_guard.ld`: data/BSS ceiling0x3ffe8000 and IRAM alias
  ceiling0x400a8000.
- Actual compiled `detpipe_validate_copy` loads source0x3ffe8000 at0x400ddcc9.
- Reviewed ELF SHA256: e4cda7fe21ca35792981a8300c6f8fe206f8284f9922815b7730b860ae750dba,
  matching the frozen verification record.
- Recorded application SHA256: d9194cfcbc2a994673fe036ce658fce64427c9626428c96cf8ab3517dd646e28.

This separate correction deliberately leaves the frozen artifact, source archive,
and checksums unchanged. It does not change a memory reservation or firmware.
It is not a diagnosis of the retention timeout.

## Independent timeout review, no root cause established

Actual target frames: pipeline command1792 bytes, acquisition64, validation
callback32, commit64 (packing inlined), energy48, main192, serial serve176,
command dispatch160. The fused commit nesting adds about96 bytes relative to
outer commit. These direct-frame measurements do not include every callee or
interrupt/window-spill path, but do not support claiming stack exhaustion merely
from the nested retention call. Configured main task stack8192; FreeRTOS canary
checking enabled, hardware end-of-stack watchpoint disabled. No stack change
proposed without measurement.

Retention packing occurs after capture stop, delay, and owner/lane/ADC/filter
restoration. It reads the previous immutable raw copy before fused validation
replaces that copy. Full-length packed size40950 bytes is9 full4096-byte pages
plus4086 bytes; source packing and page bounds are consistent. DMA/internal/8bit
allocation and ordinary-DRAM/nonoverlap checks remain. No UART or allocation call
occurs inside the validation/retention callback.

UART summary transmission uses uart_tx_chars, which synchronously writes bytes
to FIFO; it does not queue the caller's stack pointer for later access. Its
underlying tx mutex uses portMAX_DELAY, so the outer send deadline cannot bound
that mutex wait. This is a general transport limitation, not evidence that mutex
contention caused this incident. There is no observed retention-only source for
8884 NUL bytes. The saved drain contains exactly8884 zero bytes followed by the
23-byte `ESP32SDR 6 burst 16380\n` response. It contains no readable panic trace;
it neither proves nor rules out a reset, corruption, or transport fault.

No firmware edits, serial access, speculative delay, or stack modification were
made during this independent review. Retained same-image repeated hardware
trials and complete transcripts remain the appropriate discriminator.
