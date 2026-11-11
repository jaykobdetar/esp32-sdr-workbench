#!/usr/bin/env python3
"""Exercise real PyQtGraph paint callbacks; a Qt abort must fail this process."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication([])
    window = pg.GraphicsLayoutWidget()
    plot = window.addPlot()
    curve = plot.plot()
    window.nextRow()
    view = window.addViewBox()
    image = pg.ImageItem()
    view.addItem(image)
    window.show()
    ticks = 0
    x = np.arange(512)

    def repaint() -> None:
        nonlocal ticks
        curve.setData(x, np.sin(x / 20 + ticks / 10))
        image.setImage(np.sin(x[:, None] / 20 + x[None, :] / 30 + ticks / 10))
        ticks += 1
        if ticks >= 300:
            window.close()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(repaint)
    timer.start(20)
    QTimer.singleShot(20000, lambda: app.exit(2))
    result = app.exec()
    return result if result else (0 if ticks >= 300 else 1)


if __name__ == '__main__':
    raise SystemExit(main())
