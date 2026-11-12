"""Run the production SPEC command with host-side SDK/transport fault stubs."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / 'firmware/main/common'

STUBS = {
    'esp_cpu.h': '#include <stdint.h>\nuint32_t esp_cpu_get_cycle_count(void);\n',
    'dsps_fft2r.h': """#include <stdint.h>
#define ESP_OK 0
extern int16_t *dsps_fft_w_table_sc16;
int dsps_fft2r_init_sc16(int16_t *, int);
""",
    'esp_rom_crc.h': """#include <stdint.h>
#include <stddef.h>
uint32_t esp_rom_crc32_le(uint32_t, const uint8_t *, size_t);
""",
    'esp_timer.h': '#include <stdint.h>\nint64_t esp_timer_get_time(void);\n',
    'freertos/FreeRTOS.h': '',
    'freertos/task.h': 'void vTaskDelay(unsigned);\n',
}

HARNESS = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "spectrum.h"
#include "spectrum_stats.h"
#include "burst_serial.h"

unsigned spectrum_dc_mode;
int16_t *dsps_fft_w_table_sc16;
static unsigned initialized, acquired, stops, stats_initialized;
static unsigned expected_n, expected_rate;
static const char *fault;
static char output[1024];
static size_t output_size;
int dsps_fft2r_init_sc16(int16_t *w, int n) {
    (void)n;
    initialized++;
    dsps_fft_w_table_sc16 = w;
    return !strcmp(fault, "memory") ? -1 : 0;
}
uint32_t esp_cpu_get_cycle_count(void) { return 0; }
int64_t esp_timer_get_time(void) { return 0; }
uint32_t esp_rom_crc32_le(uint32_t crc, const uint8_t *data, size_t n) {
    (void)data; (void)n; return crc;
}
void vTaskDelay(unsigned n) { (void)n; }
burst_serial_port_t burst_serial_port(void) { return BURST_SERIAL_UART; }
bool burst_serial_send(const void *data, size_t n) {
    assert(output_size + n < sizeof(output));
    memcpy(output + output_size, data, n);
    output_size += n;
    output[output_size] = 0;
    return strcmp(fault, "send") != 0;
}
size_t burst_serial_try_send(const void *data, size_t n) {
    (void)data; return n;
}
bool burst_serial_stop_requested(void) {
    stops++;
    return !strcmp(fault, "stop");
}
void spectrum_stats_init(spectrum_stats_t *s) {
    stats_initialized++;
    memset(s, 0, sizeof(*s));
}
void spectrum_stats_emit(spectrum_stats_t *s, unsigned n, unsigned fs,
                         uint32_t ffts, uint32_t abandoned, uint32_t drops,
                         uint32_t late, unsigned queue,
                         bool (*send)(const void *, size_t)) {
    (void)s; (void)n; (void)fs; (void)ffts; (void)abandoned;
    (void)drops; (void)late; (void)queue; (void)send;
}
static bool acquire(unsigned n, unsigned rate, const uint32_t **words, unsigned *elapsed) {
    (void)words; (void)elapsed;
    acquired++;
    assert(n == expected_n && rate == expected_rate);
    /* A hardware fault terminates even intentionally unlimited duration 0. */
    return false;
}
int main(int argc, char **argv) {
    assert(argc == 6);
    fault = argv[2];
    expected_n = (unsigned)strtoul(argv[3], NULL, 10);
    expected_rate = (unsigned)strtoul(argv[4], NULL, 10);
    bool valid = !strcmp(argv[5], "valid");
    assert(spectrum_command(argv[1], 100, acquire));
    if (!valid) {
        assert(!strcmp(output, "ERR spec_args\n"));
        assert(initialized == 0 && acquired == 0 && stops == 0 && stats_initialized == 0);
    } else if (!strcmp(fault, "memory")) {
        assert(!strcmp(output, "ERR spectrum_memory\n"));
        assert(initialized == 1 && acquired == 0 && stats_initialized == 0);
    } else {
        assert(initialized == 1 && !strncmp(output, "SPEC ", 5));
        if (!strcmp(fault, "send")) {
            assert(acquired == 0 && stops == 0 && stats_initialized == 0);
        } else {
            assert(stats_initialized == 1 && stops == 1);
            if (!strcmp(fault, "stop")) {
                assert(acquired == 0 && strstr(output, "SPECEND 0 "));
                assert(strstr(output, " 0 1\n"));
            } else {
                assert(acquired == 1 && strstr(output, "SPECEND 1 "));
            }
        }
    }
    return 0;
}
"""


@pytest.fixture(scope='module', params=['-O0', '-O2', 'ubsan'])
def spectrum_binary(request, tmp_path_factory):
    if not shutil.which('cc'):
        pytest.skip('Host C compiler unavailable')
    folder = tmp_path_factory.mktemp('spectrum-arguments')
    for name, content in STUBS.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    source = folder / 'spectrum_arguments.c'
    source.write_text(HARNESS)
    binary = folder / 'check'
    flags = (
        ['-O2', '-fsanitize=undefined', '-fno-sanitize-recover=all']
        if request.param == 'ubsan'
        else [request.param]
    )
    subprocess.run(
        [
            'cc',
            '-std=gnu11',
            '-Wall',
            '-Wextra',
            '-Werror',
            *flags,
            '-DCONFIG_IDF_TARGET_ESP32=1',
            '-I',
            str(folder),
            '-I',
            str(COMMON),
            str(source),
            str(COMMON / 'spectrum.c'),
            '-lm',
            '-o',
            str(binary),
        ],
        check=True,
    )
    return binary


def run_command(binary, command, valid=False, fault='acquire', n=256, rate=6):
    subprocess.run(
        [str(binary), command, fault, str(n), str(rate), 'valid' if valid else 'invalid'],
        check=True,
        timeout=5,
    )


def test_malformed_optional_stats_never_acquires(spectrum_binary):
    for duration in (0, 1):
        for suffix in ('garbage', '1garbage', '-0', '+0', '4294967296', '0 0', '0 junk'):
            run_command(spectrum_binary, f'SPEC {duration} 1 1 0 6 256 {suffix}')


def test_rejects_malformed_fields_and_trailing_tokens(spectrum_binary):
    fields = ['1', '1', '1', '0', '6', '256', '0']
    for index in range(len(fields)):
        for value in ('-0', '+0', '-1', '1x', '0x1', '1.0', '4294967296', '9' * 128):
            bad = fields.copy()
            bad[index] = value
            run_command(spectrum_binary, 'SPEC ' + ' '.join(bad))
    for count in range(6):
        run_command(spectrum_binary, 'SPEC ' + ' '.join(fields[:count]))
    for suffix in (' extra', ' 0', ' \tgarbage'):
        run_command(spectrum_binary, 'SPEC ' + ' '.join(fields) + suffix)


def test_rejects_out_of_range_fields(spectrum_binary):
    for command in (
        'SPEC 86400001 1 1 0 6 256',
        'SPEC 4294967295 1 1 0 6 256',
        'SPEC 1 0 1 0 6 256',
        'SPEC 1 2 1 0 6 256',
        'SPEC 1 1 0 0 6 256',
        'SPEC 1 1 9 0 6 256',
        'SPEC 1 1 1 2 6 256',
        'SPEC 1 1 1 0 2 256',
        'SPEC 1 1 1 0 4294967295 256',
        'SPEC 1 1 1 0 6 255',
        'SPEC 1 1 1 0 6 257',
        'SPEC 1 1 1 0 6 4096',
        'SPEC 1 1 1 0 6 256 2',
    ):
        run_command(spectrum_binary, command)


def test_valid_optional_stats_and_duration_boundaries(spectrum_binary):
    for duration in (0, 1, 86400000):
        for suffix in ('', ' 0', ' 1', '   ', '  00  '):
            run_command(spectrum_binary, f'SPEC {duration} 1 1 0 6 256{suffix}', valid=True)
    for n in (256, 512, 1024, 2048):
        for rate in (0, 1, 6):
            run_command(spectrum_binary, f'SPEC 1 1 8 1 {rate} {n} 1', valid=True, n=n, rate=rate)
    run_command(spectrum_binary, 'SPEC   0001  1 1 0 6 256  ', valid=True)


@pytest.mark.parametrize('fault', ['memory', 'send', 'stop'])
def test_valid_command_faults_and_explicit_unlimited_stop(spectrum_binary, fault):
    run_command(spectrum_binary, 'SPEC 0 1 1 0 6 256 1', valid=True, fault=fault)


@pytest.mark.parametrize(
    'target', ['ESP32S2', 'ESP32S3', 'ESP32C2', 'ESP32C3', 'ESP32C6', 'ESP32C61', 'ESP32H2']
)
def test_shared_command_target_branches(spectrum_binary, target):
    # Compile each target's rates/storage/transport branches against the same
    # production command and stubs. This is not an ESP-IDF firmware build.
    folder = spectrum_binary.parent
    binary = folder / target
    subprocess.run(
        [
            'cc',
            '-std=gnu11',
            '-O2',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-fsanitize=undefined',
            '-fno-sanitize-recover=all',
            f'-DCONFIG_IDF_TARGET_{target}=1',
            '-I',
            str(folder),
            '-I',
            str(COMMON),
            str(folder / 'spectrum_arguments.c'),
            str(COMMON / 'spectrum.c'),
            '-lm',
            '-o',
            str(binary),
        ],
        check=True,
    )
    rate = 0 if target in ('ESP32S3', 'ESP32C61') else 6
    run_command(binary, f'SPEC 0 1 1 0 {rate} 256 garbage', rate=rate)
    run_command(binary, f'SPEC 1 1 1 0 {rate} 256', valid=True, rate=rate)
    run_command(binary, f'SPEC 0 1 1 0 {rate} 256 1', valid=True, fault='stop', rate=rate)
