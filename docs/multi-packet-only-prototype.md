# Finite multi-receiver packet metadata controls

This separate coordinator reuses the reviewed packet parser, finite collector,
source-denominator validator and calibration checks. It never flashes firmware.
Only separately verified `esp32-packet-only-bounded-v1finish` boards qualify.
Use two to four distinct verified receiver paths; keep identity/recovery and
flashed app-image verification separately. Paths and device information are
retained privately in the receipt.

```sh
python -m nrf_campaigns.multi_packet_only_campaign \
  --port VERIFIED_A --port VERIFIED_B --tx-serial VERIFIED_SOURCE \
  --output NEW_PRIVATE_DIRECTORY --count 32 --off-only
```

This is dry-run by default. `--run` opens hardware. First qualify every receiver
with source OFF before a bounded ON/OFF campaign. Defaults are 128 slots per
receiver, 20 ms period, cap16 and a finite 5-second source run. Optional
`--stagger-ms` adds receiver-index times that delay before each condition's
command; this is host scheduling only, not device-clock or RF synchronization.
The same delay applies to OFF and ON. Source duration must include the admission
span, maximum planned delay and at least one second slack. Actual complete END
receipt for every ON receiver must precede the conservative source deadline;
planned slack does not guarantee terminal transport completion.

One source START is shared by all ON receiver workers. Each worker writes its
own raw wire lines before parsing, with independently retained status/error.
All bounded workers are joined on failure or interruption before source restore
or receiver cleanup. A failed sibling invalidates the entire campaign; successful
siblings remain retained but cannot salvage a union recall. STOP/restore/close
failures also invalidate the result. Every receiver requires verified OFF and ON,
zero OFF packets and output-cap drops, and unchanged calibration fingerprints.

The numerator is the exact known sequence/payload union across receivers in one
source run. Address, payload pattern and air CRC are checked; shared observations
are duplicates, not additional packets. Denominator is all completed source
transmissions, including startup, slack and uncaptured periods. Fresh START,
attempted==completed and scheduled==attempted+missed are mandatory. There is no
event-level source trace. Per-board observations, unique packets, skipped slots,
incomplete/busy candidates and output drops stay explicit. Those candidate
counters are not counts of unique RF packets lost.

This is not continuous acquisition or general/Quest protocol support. A larger
union than one receiver is not by itself proof of synchronized coverage, or an
equal-condition improvement against the earlier sparse raw-IQ controls.
