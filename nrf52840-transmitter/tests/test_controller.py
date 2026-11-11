import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'host'))
from rf_tx import Transmitter
class Wire:
 def __init__(self,b):self.buf=bytearray(b);self.sent=[];self.is_open=True
 def write(self,b):self.sent.append(b)
 def flush(self):pass
 def read(self,n):
  b=bytes(self.buf[:n]);del self.buf[:n];return b
 def close(self):self.is_open=False

def tx(b):
 t=Transmitter.__new__(Transmitter);t.serial=Wire(b);t.failed=False;t.timeout=.002;return t

def test_response():
 t=tx(b'{"ok":true,"running":false}\n');assert t.status()['running'] is False

def test_timeout_poison_and_close():
 t=tx(b'{"ok":');
 with pytest.raises(TimeoutError):t.status()
 assert t.failed
 with pytest.raises(RuntimeError,match='uncertain'):t.command('START count=1 duration_ms=10')
 assert len(t.serial.sent)==1
 with pytest.raises(RuntimeError):t.close()
 assert not t.serial.is_open

def test_malformed_poison():
 t=tx(b'not json\n')
 with pytest.raises(RuntimeError):t.status()
 assert t.failed

def test_explicit_rejection_is_framed():
 t=tx(b'{"ok":false,"error":"bad_config"}\n')
 with pytest.raises(RuntimeError):t.configure(foo=1)
 assert not t.failed

def test_context_preserves_error():
 t=tx(b'')
 with pytest.raises(ValueError):
  try:raise ValueError('first failure')
  except ValueError:
   t.__exit__(ValueError,None,None)
   raise
 assert not t.serial.is_open

def test_finite_start():
 t=tx(b'')
 for n in [-1,60001]:
  with pytest.raises(ValueError):t.start(duration_ms=n)
 assert not t.serial.sent

@pytest.mark.parametrize('value', ['', 'abcd', '0123456789abcdef', '*'])
def test_missing_or_invalid_identity(value):
 import rf_tx
 with pytest.raises(ValueError):rf_tx.target_serial(value)

def test_discover_exact_identity(monkeypatch):
 import rf_tx
 from types import SimpleNamespace
 device=SimpleNamespace(device='/dev/test-only',vid=rf_tx.VID,pid=rf_tx.PID,serial_number='0123456789ABCDEF')
 monkeypatch.setattr(rf_tx.list_ports,'comports',lambda:[device])
 assert rf_tx.discover('0123456789ABCDEF')=='/dev/test-only'
 with pytest.raises(RuntimeError):rf_tx.discover('FEDCBA9876543210')
 with pytest.raises(RuntimeError):rf_tx.Transmitter('/dev/another-test-only',serial_number='0123456789ABCDEF')
 monkeypatch.setattr(rf_tx.list_ports,'comports',lambda:[device,device])
 with pytest.raises(RuntimeError):rf_tx.discover('0123456789ABCDEF')


def test_controller_accepts_verified_symlink_alias(monkeypatch, tmp_path):
 import rf_tx
 from types import SimpleNamespace
 device = tmp_path/'tty-test'
 device.touch()
 alias = tmp_path/'by-id-test'
 alias.symlink_to(device)
 observed = []
 class FakeSerial:
  def __init__(self, port, *args, **kwargs):
   observed.append(port)
  def reset_input_buffer(self):pass
 monkeypatch.setattr(rf_tx.list_ports, 'comports', lambda:[SimpleNamespace(
  device=str(device), vid=rf_tx.VID, pid=rf_tx.PID, serial_number='0123456789ABCDEF')])
 monkeypatch.setattr(rf_tx.serial, 'Serial', FakeSerial)
 monkeypatch.setattr(rf_tx.time, 'sleep', lambda _:None)
 controller = rf_tx.Transmitter(str(alias), serial_number='0123456789ABCDEF')
 assert controller.port == str(device)
 assert observed == [str(device)]
 wrong_device = tmp_path/'wrong-tty-test'
 wrong_device.touch()
 wrong_alias = tmp_path/'wrong-by-id-test'
 wrong_alias.symlink_to(wrong_device)
 with pytest.raises(RuntimeError, match='does not match'):
  rf_tx.Transmitter(str(wrong_alias), serial_number='0123456789ABCDEF')
 assert observed == [str(device)]
