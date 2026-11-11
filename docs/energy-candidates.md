# Exact-equivalent ESP32 energy kernels

This release uses the candidate implementation preserved in `firmware/main/targets/esp32/pipeline_energy_body.inc`. The original generator and its complete small input/output set are archived under [evidence/diagnostic-sources/energy-candidates](evidence/diagnostic-sources/energy-candidates/). That archive is not a replacement firmware build or a complete benchmark campaign.

## Semantics and arithmetic bounds

Aligned packed 32-bit words contain signed 10-bit I in bits 0–9 and transmitted −Q in bits 10–19. Upper metadata bits do not contribute to energy. For each complete block of 64 samples:

```
si = sum(I)
sq = sum(-Q)
squares = sum(I*I + (-Q)*(-Q))
energy = (64*squares - si*si - sq*sq) // 4096
```

The output mean is the truncated integer average of block energies; peak is the maximum block energy. The caller contract is `n <= 16380`. Incomplete blocks are excluded, so a full 16380-sample capture analyzes 16320 samples and excludes 60 tail samples from energy, not from integrity validation. No subsampling or early rounding is equivalent to this definition.

- Components lie in `[-512,511]`; a 64-component sum lies in `[-32768,32704]`.
- Each squared sum is at most `2^30`, fitting signed 32-bit. Their sum can equal `2^31`, so convert each square to unsigned before addition.
- Per-sample squared magnitude is at most `2^19`; the block sum is at most `2^25`. Its left shift by six fits unsigned 32-bit.
- Cauchy–Schwarz makes the variance numerator nonnegative. Unsigned subtraction therefore agrees with the integer result.
- Each block energy is below `2^19`; summing at most 255 blocks stays below `2^27`.

These bounds explain exactness of the operations in the source, rather than assuming floating-point equivalence. A constant signal must have zero DC-removed energy, even at full negative scale.

## Candidate identities

0: v2 baseline; 1: XOR-bias sign extension; 2: subtract-sign; 3: GCC shift-sign; 4: XOR unroll4; 5: XOR unroll8; 6: XOR dual-lane; 7: explicit Xtensa SEXT (portable fallback on the host).

The release selector exposes only 0 and 3. Candidate 3 depends on the target GCC's signed conversion/arithmetic-right-shift semantics and is not claimed to be universally ISO-C portable. Candidate 7's host fallback cannot validate its Xtensa instruction path. Code size and instruction count alone are not timing measurements.

The archived dispatcher compiles all eight candidates in default-text and IRAM-decorated variants, with `noinline,noclone,noipa` to keep distinct callable kernels. Resolve function pointers outside timing. A host section decoration is not physical ESP32 IRAM; verify final target ELF placement before interpreting hardware results. Kernel-only timings do not establish end-to-end duty, sensitivity or packet recovery.

## Regenerate the archived dispatcher

From the repository root:

```sh
python3 docs/evidence/diagnostic-sources/energy-candidates/generate_dispatcher.py
cmp docs/evidence/diagnostic-sources/energy-candidates/energy_kernel_body.inc firmware/main/targets/esp32/pipeline_energy_body.inc
```

The generator reads its sibling `detector_energy_candidates.h`, removes its first `#pragma once`, and writes sibling `energy_kernel_body.inc` plus `energy_candidates_runtime.h`. It does not directly write the release's renamed `pipeline_energy_body.inc`; that release file is byte-identical to the archived generated body at publication. After intentionally changing the source, review and explicitly integrate any updated body. Running the generator alone is not a target build or equivalence test.

The archive includes an independent 64-bit comparison helper. The public firmware regression tests cover exact arithmetic; see [validation](validation.md) and the published [evidence](evidence/). Original full experiment runners, all generated stress cases, target objects/disassemblies and every raw RF fixture are not implied to be present merely because the generator is available. Historical campaign reports are evidence of their recorded runs, not tests re-executed during publication.
