# Host recording publication and spectrum gain

## SigMF recording writes

`save_capture` stages the entire payload and JSON metadata in a private temporary
directory on the destination filesystem, flushes and syncs both files, then
publishes the data followed by the metadata. Metadata is the completion marker;
discover recordings by their `.sigmf-meta` files, not their data files.

Publication uses exclusive hard links rather than replacement renames. Existing
files (including dangling symlinks) and competing saves are not overwritten.
Serialization, payload-write and sync failures remove the private staging files
and leave the recording basename available for retry. If metadata publication
fails, the just-published data file is removed only if its device and inode still
match the staged file. A concurrently replaced file is left alone.

This requires a filesystem supporting same-filesystem hard links. There is no
unsafe overwrite fallback. The pair is not a filesystem transaction: a process
kill or power loss between publications can leave orphan data, and directory
entries are not synced for crash durability. Cleanup also requires a writable
filesystem. As with ordinary filesystem operations, callers must not allow
untrusted processes to mutate the destination directory; the identity check and
unlink are not atomic against arbitrary concurrent replacements.

The SigMF schema, basename rules, return value and no-overwrite contract are
unchanged. Successful replay still reads little-endian complex float32 data.

## SPC1 spectrum gain

Each decoded spectrum frame now includes `gain`: the unsigned, eight-bit value
at byte 23 of the CRC-validated SPC1 frame. It is preserved verbatim, including
zero and 255, rather than inferred from the requested manual gain setting.

The current common firmware takes this byte from the first raw sample's upper
bits for the first capture merged into the output frame. The S31 path takes the
first contributing job's sample gain metadata. It is not a calibrated dB gain,
not a guarantee that gain stayed constant across the merged frame, and not a
replacement for separate gain-mode/readback telemetry.

This is an additive field in the host frame dictionary and serialized results.
There is no wire-format or protocol-version change; existing frame keys and
power-code interpretation are unchanged. Older saved results may omit `gain`;
consumers reading historical data should treat a missing field as unknown.
