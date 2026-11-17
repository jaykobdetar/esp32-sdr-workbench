# Calibration lease preflight (pending independent review)

No firmware edits/build or hardware. Proposed lease is **narrower** than originally suggested.

## Excluded from critical region

Do not call prepare_rx, tune_rx, rx_recalibration_stale or rx_recalibrate while leased: these may reacquire the same nonrecursive PHY mutex. Perform ordinary RX/PBUS/gain/LO preparation and filter_apply before acquiring the lease. All ROM I2C functions, filter_restore, allocation/free, UART, task-delay/idle hooks, decoder and copying full input remain outside it. If initial readiness/freshness is absent, reject instead of preparing a new calibration. Preparation must have an explicit stale-free path; original prepare_rx cannot be assumed side-effect-free.

## Proposed narrow call graph

1. Before lease: normal receiver prepared, filter applied, buffer sentinel clear complete, UART already drained; check STOP.
2. Lease begin gets phy_get_lock handle. Require nonzero initialized handle, then _lock_try_acquire once. Never lazy initialize a copied zero handle, never unbounded lock wait. Contention fails before trigger. Check calibrated flag/live-table equality directly under lock; copy152 DC bytes, not via public stale function.
3. While leased: direct register reads/writes to force ADC, save owner/byte-select, map aperture, arm/trigger, poll completion with existing20ms bound, stop and restore ownership/byte-select/ADC. Only existing esp_timer_get_time, esp_rom_delay_us and DPORT read helper calls. No callback, logging, scheduling wait or dependency on another task needing PHY lock. Acquire failure restores filter outside lease; every acquired path restores hardware before release.
4. After restoration but before unlock: copy152 live DC bytes and compare captured fingerprint/freshness. Release exactly once. Outside lock restore filter and check STOP; failures invalidate generation, no decode success.

This preserves relative hardware setup ordering except moving sentinel clearing before lease admission and placing lock around direct-only section. It does not require PHY progress to set MAC completion according to the existing register-driven path; this inference still needs hardware qualification. No static proof of hardware forward progress is claimed.

## Source findings

Pinned SDK /home/jaykob/Documents/Codex/2026-11-10/i-ha/work/esp-idf commit25fe69f946311abdaf9ad56591f25fedbc20ac98.
- components/esp_phy/src/phy_init.c: phy_get_lock returns s_phy_access_lock. esp_phy_enable holds it across PHY initialization; enable/disable and frequency/control operations shown in that source cooperate. Existing application rx_recalibrate takes this same handle around rx_recalibrate_locked and baseline-table snapshots.
- components/esp_libc/src/locks.c: _lock_try_acquire uses lock_acquire_generic with delay0, returns0 on acquisition and-1 otherwise. A zero handle may allocate lazily, hence explicit nonzero rejection in proposed API. Scheduler must already be running in command context.
- components/esp_timer/src/esp_timer_impl_lac.c: esp_timer_get_time aliases counter-register read divided by constant; no PHY mutex/task wait. Counter consistency reread is not a hard realtime bound under arbitrary interrupts.
- components/soc/esp32/include/soc/dport_access.h: DPORT reads use APB preread and short interrupt masking, expressly no other-CPU stall; writes require no protection. Preserve original helper, not new broad interrupt disabling.
- ROM delay is existing bounded delay primitive, not a task service. ROM I2C/PBUS routines excluded because this ELF provides addresses, not their full call bodies.

## Exclusion strength and unresolved writer scope

Identified controlled application DC writer is rx_recalibrate_locked invoked only under rx_recalibrate's PHY lock; startup PHY registration is reached under esp_phy_enable's lock. Existing ESP32 archive DC symbols are phy_rxbb_dc16bytes and phy_rxrf_dc136bytes. Their vendor-internal updates are not intercepted by the existing application's generation wrappers. SDK explicitly notes ESP32 PLL tracking in modem interrupt context. Thus this lease is not a universal calibration epoch or autonomous-radio freeze, and every vendor/ROM writer has NOT been proven to honor it. A changed table is detected at snapshots; change-and-revert from an uncontrolled writer is not excluded. Do not label a fingerprint a monotonic calibration generation.

Parent must accept this documented writer scope or require more static vendor analysis before implementation. No implicit downgrade to snapshot-only universal claims. Independent review requested before source changes/build.
