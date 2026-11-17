"""Exercise the shell entrypoints without importing Qt, starting a process on a device, or serial I/O."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


@pytest.mark.parametrize(
    'script,module',
    [('launch.sh', 'gui'), ('launch-lab.sh', 'lab_gui'), ('launch-studio.sh', 'studio_gui')],
)
@pytest.mark.parametrize('selected', ['explicit', 'venv', 'fallback'])
def test_checkout_launchers_preserve_environment_and_argv(tmp_path, script, module, selected):
    root = tmp_path / 'checkout with spaces'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('launcher-common.sh', script):
        shutil.copy2(SCRIPTS / name, scripts / name)
    bins = tmp_path / 'bin'
    choices = {
        'explicit': bins / 'custom python',
        'venv': root / '.venv/bin/python',
        'fallback': bins / 'python3',
    }
    for name, path in choices.items():
        if name == 'venv' and selected == 'fallback':
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$0" "$PWD" "$PYTHONPATH" "$@"\n')
        path.chmod(0o755)
    env = dict(
        os.environ,
        PATH=f'{bins}:{os.environ["PATH"]}',
        PYTHONPATH='/other path',
        PYTHON=str(choices['explicit']) if selected == 'explicit' else '',
    )
    output = subprocess.check_output(
        ['bash', str(scripts / script), '--demo', 'two words', '*'],
        cwd=tmp_path,
        env=env,
        text=True,
    ).splitlines()
    assert output == [
        str(choices[selected]),
        str(root),
        f'{root}:/other path',
        '-m',
        'sdr_research.' + module,
        '--demo',
        'two words',
        '*',
    ]
