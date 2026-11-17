"""Read-only inspection of one retained or replayed capture, shared by the three Qt views."""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from .analysis import endpoint_counts, spectrum

# Share of samples on an ADC endpoint code above which the viewer flags likely clipping.
CLIP_WARN_PERCENT = 1.0


def endpoint_text(capture):
    """Status fragment giving one capture's ADC endpoint share; flags likely clipping."""
    percent = endpoint_counts(capture.iq, capture.bits)['either_component_endpoint_percent']
    warning = ' · LIKELY CLIPPING' if percent >= CLIP_WARN_PERCENT else ''
    return f'ADC endpoints {percent:.2f}%{warning}'


class InspectionWindow(QtWidgets.QDialog):
    def __init__(self, capture, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Capture inspection · no transmitter attribution')
        self.resize(1100, 760)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(
            f'{capture.timestamp} · {capture.frequency_hz / 1e6:.3f} MHz · '
            f'{capture.sample_rate_hz / 1e6:g} MS/s · {len(capture.iq):,} samples · '
            f'{endpoint_text(capture)}'
        )
        layout.addWidget(label)
        if capture.metadata.get('detector_summary'):
            layout.addWidget(
                QtWidgets.QLabel(
                    'Detector strongest retained capture. Timestamp is host run start, NOT exact RF event time.'
                )
            )
        plots = pg.GraphicsLayoutWidget()
        layout.addWidget(plots)
        iq = np.asarray(capture.iq)
        # Bound drawing cost for unusually large replay recordings.
        stride = max(1, len(iq) // 30000)
        t = np.arange(len(iq))[::stride] / capture.sample_rate_hz * 1e6
        p = plots.addPlot(title='Raw I/Q')
        p.setLabel('bottom', 'Time', units='µs')
        p.addLegend()
        p.plot(t, iq.real[::stride], pen='#58b9ff', name='I')
        p.plot(t, iq.imag[::stride], pen='#ffb454', name='Q')
        p = plots.addPlot(title='Power versus time')
        p.setLabel('bottom', 'Time', units='µs')
        p.setLabel('left', 'Power', units='dBFS')
        p.plot(t, 10 * np.log10(np.maximum(np.abs(iq[::stride]) ** 2, 1e-14)), pen='#83e1ab')
        plots.nextRow()
        p = plots.addPlot(title='FFT (mean DC removed)')
        p.setLabel('bottom', 'Frequency offset', units='MHz')
        p.setLabel('left', 'Power', units='dBFS')
        offsets, power = spectrum(
            iq, capture.sample_rate_hz, nfft=min(1024, len(iq)), remove_dc=True
        )
        p.plot(offsets / 1e6, power, pen='#58b9ff')
        p = plots.addPlot(title='Constellation · not a decoded modulation')
        p.setLabel('bottom', 'I')
        p.setLabel('left', 'Q')
        p.plot(
            iq.real[::stride],
            iq.imag[::stride],
            pen=None,
            symbol='o',
            symbolSize=2,
            symbolBrush='#58b9ff80',
        )
        p.setAspectLocked()
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
