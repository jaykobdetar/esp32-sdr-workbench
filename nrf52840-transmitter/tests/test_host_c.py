"""Run the transmitter's real C tests under host sanitizers, without hardware."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIRMWARE = Path(__file__).resolve().parents[1] / 'firmware'


@pytest.mark.parametrize('name', ['schedule', 'stop_control', 'crc32'])
def test_c_module(name, tmp_path):
    executable = tmp_path / name
    subprocess.run(
        [
            'cc',
            '-std=c11',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-fsanitize=undefined',
            '-fno-sanitize-recover=all',
            '-I' + str(FIRMWARE),
            str(FIRMWARE / (name + '.c')),
            str(FIRMWARE / ('test_' + name + '.c')),
            '-o',
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_offline_parser_status(tmp_path):
    # The legacy harness writes relative to cwd. Isolate generated files from sources.
    for source in FIRMWARE.iterdir():
        if source.is_file():
            shutil.copyfile(source, tmp_path / source.name)
    subprocess.run([sys.executable, 'test_offline.py'], cwd=tmp_path, check=True)
