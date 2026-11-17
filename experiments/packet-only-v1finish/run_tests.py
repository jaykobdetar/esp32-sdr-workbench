#!/usr/bin/env python3
"""Native C mocks/fixtures with ASan+UBSan; no device/network access."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    pins = json.loads((HERE / 'manifest.json').read_text())
    for name, digest in pins['tests_sha256'].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Test fixture mismatch: ' + name)
    with tempfile.TemporaryDirectory(prefix='packet-only-tests-') as tmp:
        work = Path(tmp)
        source = work / 'candidate'
        subprocess.run([sys.executable, str(HERE / 'materialize.py'), str(source)], check=True)
        target = source / 'firmware/main/targets/esp32'
        env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
        for name in ('slot_audit', 'command', 'packet'):
            binary = work / ('test-' + name)
            command = [
                os.environ.get('CC', 'cc'),
                '-std=c11',
                '-O2',
                '-Wall',
                '-Wextra',
                '-Werror',
                '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all',
                '-I' + str(HERE / 'tests/mocks'),
                '-I' + str(target),
                str(HERE / ('tests/test_' + name + '.c')),
            ]
            if name == 'packet':
                command += [str(target / 'packet.c'), '-lm', '-Wconversion']
            subprocess.run(command + ['-o', str(binary)], check=True)
            subprocess.run([str(binary)], env=env, check=True)
    print('All packet-only native tests passed. No hardware accessed.')


if __name__ == '__main__':
    main()
