"""Static artifact audit, not runtime admission. No device access."""

import hashlib
import json
import struct
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX = '/home/jaykob/Documents/Codex/2026-11-10/i-ha/work/idf-tools/tools/xtensa-esp-elf/esp-16.1.0_20260609/xtensa-esp-elf/bin/xtensa-esp32-elf-'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def inspect(mode):
    base = ROOT / 'research-output' / f'build-{mode}'
    path = base / 'esp_sdr.elf'
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x01\x01'
    off = struct.unpack_from('<I', data, 32)[0]
    size, n, namesidx = struct.unpack_from('<HHH', data, 46)
    assert size == 40
    sections = [struct.unpack_from('<10I', data, off + i * size) for i in range(n)]
    strings = sections[namesidx]
    strings = data[strings[4] : strings[4] + strings[5]]
    out = []
    for s in sections:
        name = strings[s[0] :].split(b'\0')[0].decode()
        a, length = s[3], s[5]
        if s[2] & 2 and length:
            assert not (a < 0x3FFF8000 and a + length > 0x3FFE8000), (name, 'DRAM aperture')
            assert not (a < 0x400B8000 and a + length > 0x400A8000), (name, 'IRAM alias')
            out.append(dict(name=name, address=hex(a), size=length))
    nm = subprocess.check_output([PREFIX + 'nm', '-S', str(path)], text=True)
    selected = {}
    for line in nm.splitlines():
        p = line.split()
        if len(p) == 4 and (
            p[3].startswith(('px_', 'paused_calibration'))
            or p[3] in ('s_phy_access_lock', 'reserved_region_esp32_rf_dump')
        ):
            selected[p[3]] = dict(address=int(p[0], 16), size=int(p[1], 16), kind=p[2])
    assert 's_phy_access_lock' in selected
    if mode == 'OFF':
        assert not any(k.startswith(('px_', 'paused_calibration')) for k in selected)
    else:
        assert 'px_keep' in selected and 'paused_calibration_begin' in selected
        for v in selected.values():
            if v['kind'].lower() == 'b':
                assert v['address'] + v['size'] <= 0x3FFE8000
    sym = selected['reserved_region_esp32_rf_dump']
    a = sym['address']
    s = next(s for s in sections if s[3] <= a < s[3] + s[5] and s[1] != 8)
    raw = data[s[4] + a - s[3] : s[4] + a - s[3] + 8]
    assert struct.unpack('<II', raw) == (0x3FFE8000, 0x3FFF8000)
    h = (base / 'esp-idf/main/generated/build_version.h').read_text()
    version = json.loads(
        json.loads(h.split('ESP_SDR_VERSION_RECORD ', 1)[1]).split('ESP-SDR-VERSION:', 1)[1]
    )
    assert version['firmware_variant'] == (
        'esp32-paused-extract-research-v1' if mode == 'ON' else 'esp32-core1-banks-experimental-v9'
    )
    assert version.get('paused_packet_extract_protocol') == (1 if mode == 'ON' else None)
    return dict(
        elf_sha256=sha(data),
        app_sha256=sha((base / 'esp_sdr.bin').read_bytes()),
        app_bytes=(base / 'esp_sdr.bin').stat().st_size,
        version=version,
        symbols=selected,
        allocated_sections=out,
    )


with tarfile.open(
    '/home/jaykob/esp32-default-validation/v9-source-checkpoint/source.tar.gz'
) as tar:
    r = 'firmware/main/targets/esp32/receiver.c'
    old = tar.extractfile(r).read().decode()
    new = (ROOT / r).read_text()
    new = new.replace(
        '#ifdef PAUSED_PACKET_EXTRACT\n#include "paused_extract.h"\n#endif\n\n', ''
    ).replace(
        '#ifdef PAUSED_PACKET_EXTRACT\n    if (paused_extract_command(line)) return;\n#endif\n', ''
    )
    assert new == old, 'legacy receiver source changed beyond guarded hooks'
    r = 'firmware/main/common/rx_calibration_state.c'
    old = tar.extractfile(r).read().decode()
    new = (ROOT / r).read_text()
    assert new[: new.index('#if defined(PAUSED_PACKET_EXTRACT)')].rstrip() == old.rstrip()
    for r in [
        'firmware/main/common/burst_serial.c',
        'firmware/main/common/burst_serial.h',
        'firmware/main/targets/esp32/receiver_caps.h',
        'firmware/main/targets/esp32/sram_guard.ld',
        'sdr_research/calibration.py',
    ]:
        assert (ROOT / r).read_bytes() == tar.extractfile(r).read(), r
out = {mode: inspect(mode) for mode in ('OFF', 'ON')}
out['limits'] = (
    'Static section/handle-variable/reservation/source checks only. Heap object addresses and complete task/ISR stack bounds require runtime qualification; single-address predicates do not prove full objects. No cache-disable, timing, RF, device or default qualification.'
)
(ROOT / 'research-output/elf-audit/summary.json').write_text(json.dumps(out, indent=2) + '\n')
print('static ON/OFF source/ELF audit PASS')
