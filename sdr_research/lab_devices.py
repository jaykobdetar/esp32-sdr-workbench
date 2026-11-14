"""Passive USB discovery; listing never opens, resets or transmits on a port."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from serial.tools import list_ports


@dataclass(frozen=True)
class Device:
    kind: str
    port: str
    device: str
    description: str
    location: str
    serial_number: str | None
    vid: int | None = None
    pid: int | None = None

    @property
    def key(self) -> str:
        return self.port

    @property
    def role(self) -> str:
        return self.kind

    @property
    def serial(self) -> str | None:
        return self.serial_number

    @property
    def label(self) -> str:
        return f'{self.kind.title()} · {self.description} · {self.location or self.device}'


def discover_devices() -> list[Device]:
    """Prefer location paths: identical CP2102 serials must not alias one receiver."""
    locations: dict[str, str] = {}
    for path in sorted(Path('/dev/serial/by-path').glob('*')):
        if path.exists():
            locations.setdefault(str(path.resolve()), str(path))
    result = []
    for port in list_ports.comports():
        if port.vid is None and port.pid is None and not port.location:
            continue  # Legacy ttyS placeholders are not attached USB radio devices.
        pair = (port.vid, port.pid)
        kind = (
            'transmitter'
            if pair == (0x2886, 0xF010)
            else 'receiver'
            if pair == (0x10C4, 0xEA60)
            else 'serial'
        )
        result.append(
            Device(
                kind=kind,
                port=locations.get(str(Path(port.device).resolve()), port.device),
                device=port.device,
                description=port.description or 'Serial device',
                location=port.location or '',
                serial_number=port.serial_number,
                vid=port.vid,
                pid=port.pid,
            )
        )
    return sorted(result, key=lambda item: (item.kind, item.port))
