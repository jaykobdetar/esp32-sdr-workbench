#!/usr/bin/env python3
"""Run preserved tests in temporary copies, relocating only historical fixture paths."""

import pathlib
import shutil
import subprocess
import sys
import tempfile

R = pathlib.Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='sdr-publication-tests-') as tmp:
    d = pathlib.Path(tmp)
    h = d / 'host'
    shutil.copytree(R / 'host', h)
    t = h / 'frozen-collector/test_compact_collector.py'
    old = '/home/jaykob/esp32-pex-collector-candidate/collector-v1-final/expected-version.json'
    s = t.read_text()
    assert s.count(old) == 1
    t.write_text(s.replace(old, str(h / 'frozen-collector/legacy-expected-version.json')))
    for cwd in (h, h / 'frozen-collector'):
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'], cwd=cwd, check=True)
    source = d / 'compact'
    subprocess.run(
        [sys.executable, str(R / 'materialize.py'), 'compact-v2', str(source)], check=True
    )
    t = source / 'research/compact/test_codec.py'
    s = t.read_text()
    old = '/home/jaykob/esp32-pex-collector-candidate/collector-v1-final'
    assert s.count(old) == 1
    t.write_text(s.replace(old, str(R / 'fixtures/legacy')))
    subprocess.run([sys.executable, str(t)], cwd=t.parent, check=True)
