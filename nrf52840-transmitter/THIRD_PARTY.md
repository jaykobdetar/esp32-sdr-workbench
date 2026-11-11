# Source provenance and licenses

The application and host tooling originate from this project's nRF52840 transmitter work. Repository licensing applies to original project code. Files retain any more-specific upstream notices.

`firmware/cdc_device_patched.c` is derived from TinyUSB `src/class/cdc/cdc_device.c` at commit `23df777b301af128d3543e286cd865212214b44d`, https://github.com/hathach/tinyusb . Its full MIT license and Ha Thach copyright notice are retained at the top of the file; trailing whitespace in the opening comment was normalized. The local modification checks DTR before removing FIFO bytes and caps each transfer at 63 bytes to force a short packet; main-loop flushing/backpressure fixes are in application code. This is the only copied third-party source in this directory. Do not replace its MIT notice with the repository-wide license.

Build dependencies are downloaded separately from their official source repositories and pinned in `dependencies.json`:

- Makerdiary UF2 bootloader: `4d08cbb6150a833f146531fa787c3c28fa3ffabb`. Used as the dependency layout, not a replacement bootloader. See upstream LICENSE and individual file notices.
- Nordic nrfx: `7a4c9d946cf1801771fc180acdbf7b878f270093`. Nordic/ARM startup, chip headers and SystemInit are used. Individual files have their own license notices, including ARM Apache-2.0 notices and Nordic notices. Preserve those licenses when distributing dependency source or linked binaries.
- TinyUSB: `23df777b301af128d3543e286cd865212214b44d`. USB stack is MIT; bundled CMSIS headers have ARM notices. Consult individual files and upstream licenses.

A rebuild is not promised bit-reproducible across toolchain versions. The packager records the compiler string and exact input hashes. The historical 0.2.2 firmware source is retained; public edits generalize build paths/host target selection and packaging. No private recovery files, historical binary snapshots, ELF debug paths, raw hardware logs, or device identifiers are included here. Build artifacts are generated locally and ignored by Git. Any subsequent binary redistribution must include applicable upstream notices and satisfy their terms.
