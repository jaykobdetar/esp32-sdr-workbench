"""All optional ESP32 CAPS combinations retain a complete, parseable line."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / 'main/targets/esp32'


@pytest.mark.parametrize('compat', [0, 1])
@pytest.mark.parametrize('health', [0, 1])
def test_capabilities_bypass_printf_limit(tmp_path, compat, health):
    # Reuse the actual optional token from the health header, not its length.
    token = re.search(
        r'#define DETPIPE_HEALTH_CAPABILITY ("[^"\n]+")',
        (ROOT / 'pipeline_health.h').read_text(),
    ).group(1)
    receiver = (ROOT / 'receiver.c').read_text()
    caps_branch = receiver.split('if (!strcmp(line, "CAPS"))', 1)[1].split('else if', 1)[0]
    source = tmp_path / 'caps.c'
    source.write_text(
        '#include <stdio.h>\n#include <string.h>\n'
        f'#define CONFIG_ESP_SDR_CP2102_VIEWER_COMPAT {compat}\n'
        f'#define DETPIPE_HEALTH_CAPABILITY {token if health else chr(34) * 2}\n'
        f'#include "{ROOT / "receiver_caps.h"}"\n'
        'static void burst_serial_send(const void*p,size_t n){fwrite(p,1,n,stdout);}\n'
        f'int main(void){{{caps_branch}return 0;}}\n'
    )
    binary = tmp_path / 'test'
    subprocess.run(
        ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)],
        check=True,
    )
    line = subprocess.check_output([str(binary)])
    assert line.endswith(b'\n') and line.count(b'\n') == 1 and b'\0' not in line
    assert line.startswith(b'CAPS ') and line.endswith(b'IQ8\n')
    capabilities = line.decode('ascii').split()[1:]
    assert len(capabilities) == len(set(capabilities))
    assert ('UARTBAUD' in capabilities) == (not compat)
    assert ('DETPIPEHEALTH' in capabilities) == bool(health)
    assert {'DSTREAMIQ', 'DSTREAMIDLEWAKE', 'BGPOLICY'} <= set(capabilities)
    if not compat and health:
        assert len(line) > 255  # The exact configuration that used to truncate.
