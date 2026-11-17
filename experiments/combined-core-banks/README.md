# Opt-in combined core/bank experiment

**Experimental finite diagnostics, not the default firmware or a continuous receiver.**
The measured combination places the capture/detector loop on CPU1 and alternates
the MAC's two 32 KiB capture banks. An otherwise identical unicore control isolates
the CPU-configuration change. The default source remains verified v7.

Read the [results and limitations](../../docs/evidence/combined-core-banks/README.md).
All 24 scheduled combined trials had 100% nominal sample-window union, but each
lasted only 0.8192–0.9216 seconds. Full-packet opportunity was lower, full-session
coverage much lower, and only final snapshots were retained. Free-running pairs
regressed. This is not 100% packet recall, an RF timing guarantee, or a long soak.

## Offline checks

```sh
python scripts/verify_combined_banks.py
python -m pytest -q tests/test_combined_bank_experiment.py
```

The evidence verifier recomputes trace CRCs, independently bracketed RF clock fits,
packet-byte/air-CRC proofs, nominal timing and whole-session coverage. Raw RF,
private recovery images, calibration contents, physical USB locations and device
identifiers are excluded. No verification command opens a radio.

## Deliberate source preparation and build

Use a full-history checkout (`git fetch --unshallow` if applicable). The helper
creates a **new detached worktree outside the current checkout**, at pinned main
`d23ddddeaabee46d340caba60b038f39946cd534`, whose tree matches measured source
`9e8dd3801e1edb2b1651ee5097de438a138253df`. It checks the patch and measured C-source
hashes. It does not flash anything or alter the default source.

```sh
python scripts/prepare_bank_experiment.py /tmp/esp32-bank-combined --variant combined
# Or a separate destination with --variant unicore for the matched control.
python -m pytest -q /tmp/esp32-bank-combined/firmware/tests/test_bank_combined.py
# Activate the pinned ESP-IDF environment as in docs/firmware-build.md first.
python /tmp/esp32-bank-combined/firmware/tools/build_firmware.py \
  --profile esp32 --version esp32-bank-core1-combined-v5 --jobs 2 \
  --build-root /tmp/bank-build --output /tmp/bank-artifacts
```

CI compiles both experimental configurations in addition to the unchanged default
and historical retention image. These fresh builds have different build metadata;
their bytes are not claimed identical to the recorded hardware-tested hashes.

`BANKRUN count fused` is the free-running diagnostic. `BANKAT count fused deadline_us
period_ns` is the scheduled diagnostic. Count is 2–1024; period is 750,000–2,000,000 ns;
the requested start must be 1 ms–2 s in the future. The tested collector uses 1024,
fused=0 and periods 800/820/850/900 us. `BANKGET` returns the final validated snapshot
and releases it; `BANKDROP` releases unused retention. Invalid arguments, stale
calibration, corruption, timeout and STOP fail closed. Each active capture has a
20 ms timeout; the overall acquisition has a 5 s cap. This bounded diagnostic does
not implement persistent paired streaming or an on-device packet decoder. The
rejected fused kernel remains available only for reproducibility and was not used
in the matched trials.

## Hardware campaign: explicit opt-in only

Do not run this without owner-authorized receivers, a bounded test source and a
verified per-device recovery plan. Build and inspect the intended app first. The
collector never flashes firmware. Supply explicit `SDR_RX_A`, `SDR_RX_B` and
`NRF_SERIAL`; optional `SDR_REPOSITORY` selects the host source checkout. It checks
actual firmware variants and core identity. The default invocation is a dry run:

```sh
python experiments/combined-core-banks/run_campaign.py /tmp/new-bank-results \
  --variant esp32-bank-core1-combined-v5
# Add --run only after explicitly configuring and authorizing the hardware.
```

With `--run`, it actively configures both radios and a 2440 MHz, 0 dBm, 2 Mbps known
transmitter, runs bounded ON/OFF trials and RF anchors, saves private raw IQ in the
new output directory, stops the source and restores its prior operational settings.
Receiver test tuning remains selected afterward; restore the user's settings and
original app in a separate verified cleanup. Do not use `python -O`.

The two tested boards had different application offsets (`0x10000` / `0x100000`).
Never copy a partition table/calibration image between boards, use a generic
mass-flash command, or overwrite NVS. This PR contains no flashing tool, firmware
binary, recovery dump or automatic updater. Both tested boards were restored to
the original verified v7 app after collection. This publication performs no
hardware actions.
