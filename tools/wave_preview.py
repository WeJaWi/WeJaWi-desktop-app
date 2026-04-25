# tools/wave_preview.py
# Preview widget for Sound Waves: drag/resize, gaps, rounded bars, styles.

from __future__ import annotations
import os, math, tempfile, subprocess, shutil, time
from typing import Tuple, Optional
from PyQt5 import QtWidgets, QtCore, QtGui

HANDLE_SIZE = 10
MAX_CHANNEL_ROWS = 4

class WavePreviewWidget(QtWidgets.QWidget):
    geometryChanged = QtCore.pyqtSignal(int,int,int,int)  # x,y,w,h (video pixels)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._video_w = 1280
        self._video_h = 720
        self._pix: Optional[QtGui.QPixmap] = None
        self._box = QtCore.QRect(0, self._video_h - 220 - 48, self._video_w, 220)
        self._dragging = False
        self._resizing = False
        self._resize_handle = None
        self._style = "sticks"   # "sticks", "rounded", "line", "spectrum"
        self._color = QtGui.QColor("#00FFCC")
        self._alpha = 0.85
        self._bar_px = 8
        self._gap_px = 2
        self._round_px = 4
        self._split_channels = False
        self._channel_count = 1
        self._amp_scale = 'lin'
        self._smooth_mult = 1.0
        self._bg_opacity = 0.25
        self._anim_t = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # --- API ---
    def setVideoMeta(self, w: int, h: int, snapshot_path: Optional[str] = None):
        self._video_w, self._video_h = max(2, w), max(2, h)
        if snapshot_path and os.path.isfile(snapshot_path):
            self._pix = QtGui.QPixmap(snapshot_path)
        else:
            self._pix = None
        bh = min(max(120, self._video_h // 4), 300)
        self._box = QtCore.QRect(0, self._video_h - bh - 48, self._video_w, bh)
        self.update()

    def setStyle(self, style: str): self._style = style; self.update()
    def setColor(self, qcolor: QtGui.QColor, alpha: float):
        self._color = qcolor; self._alpha = max(0.1, min(1.0, alpha)); self.update()
    def setBgOpacity(self, a: float): self._bg_opacity = max(0.0, min(0.9, a)); self.update()
    def setBarWidth(self, px: int): self._bar_px = max(2, min(40, int(px))); self.update()
    def setGapWidth(self, px: int): self._gap_px = max(0, min(20, int(px))); self.update()
    def setRoundness(self, px: int): self._round_px = max(0, min(20, int(px))); self.update()

    def setSplitChannels(self, enabled: bool):
        enabled = bool(enabled)
        if self._split_channels != enabled:
            self._split_channels = enabled
            self.update()

    def setAmplitudeScale(self, scale: str):
        scale_val = (scale or 'lin').lower()
        if scale_val not in {'lin', 'log', 'sqrt', 'cbrt'}:
            scale_val = 'lin'
        if self._amp_scale != scale_val:
            self._amp_scale = scale_val
            self.update()

    def setSmoothingMultiplier(self, mult: float):
        try:
            value = float(mult)
        except Exception:
            value = 1.0
        value = max(0.0, value)
        if abs(self._smooth_mult - value) > 1e-3:
            self._smooth_mult = value
            self.update()

    def setChannelCount(self, count: int):
        try:
            value = int(count)
        except Exception:
            value = 1
        value = max(1, min(MAX_CHANNEL_ROWS, value))
        if self._channel_count != value:
            self._channel_count = value
            self.update()

    def setBox(self, x: int, y: int, w: int, h: int):
        self._box = QtCore.QRect(x, y, max(10, w), max(40, h))
        self.geometryChanged.emit(self._box.x(), self._box.y(), self._box.width(), self._box.height())
        self.update()

    def getBox(self) -> Tuple[int,int,int,int]:
        b = self._box; return b.x(), b.y(), b.width(), b.height()

    # --- Rendering ---
    def sizeHint(self): return QtCore.QSize(960, 540)
    def _tick(self):
        step = 0.033
        if self._smooth_mult <= 0:
            step *= 2.0
        else:
            step /= (0.4 + self._smooth_mult)
        self._anim_t += step
        self.update()

    def _canvas_rect(self) -> QtCore.QRect:
        if self._video_w <= 0 or self._video_h <= 0: return self.rect()
        wr = self.width() / self._video_w; hr = self.height() / self._video_h
        scale = min(wr, hr)
        w = int(self._video_w * scale); h = int(self._video_h * scale)
        x = (self.width() - w) // 2; y = (self.height() - h) // 2
        return QtCore.QRect(x, y, w, h)

    def _to_widget(self, x: int, y: int) -> QtCore.QPoint:
        c = self._canvas_rect()
        sx = c.width() / max(1, self._video_w); sy = c.height() / max(1, self._video_h)
        return QtCore.QPoint(c.x() + int(x * sx), c.y() + int(y * sy))

    def _rect_to_widget(self, r: QtCore.QRect) -> QtCore.QRect:
        p1 = self._to_widget(r.x(), r.y()); p2 = self._to_widget(r.x()+r.width(), r.y()+r.height())
        return QtCore.QRect(p1, p2)

    def _channel_rows(self) -> int:
        if not self._split_channels:
            return 1
        return max(1, min(MAX_CHANNEL_ROWS, self._channel_count))

    def _row_rects(self, wb: QtCore.QRect, rows: int):
        if rows <= 0:
            return []
        rects = []
        total_h = max(1, wb.height())
        prev = 0
        for i in range(rows):
            if i == rows - 1:
                h = total_h - prev
            else:
                h = int(round((i + 1) * total_h / rows)) - prev
            if h <= 0:
                h = 1
            rects.append(QtCore.QRect(wb.x(), wb.y() + prev, wb.width(), h))
            prev += h
        return rects

    def _shape_amplitude(self, value: float) -> float:
        sign = 1.0 if value >= 0 else -1.0
        x = min(1.0, max(0.0, abs(value)))
        if self._amp_scale == 'sqrt':
            shaped = math.sqrt(x)
        elif self._amp_scale == 'cbrt':
            shaped = x ** (1.0 / 3.0)
        elif self._amp_scale == 'log':
            shaped = math.log1p(x * 9.0) / math.log(10.0)
        else:
            shaped = x
        return sign * shaped

    def _channel_amplitude(self, channel_index: int, pos_norm: float) -> float:
        speed = 1.8
        if self._smooth_mult > 0:
            speed /= (0.6 + self._smooth_mult)
        else:
            speed *= 1.4
        t = self._anim_t * speed
        base_phase = pos_norm * (6.0 + channel_index * 0.5)
        wave = math.sin(base_phase + t)
        wave += 0.45 * math.sin(base_phase * 0.6 - t * 0.7 + channel_index * 0.4)
        wave += 0.25 * math.sin(base_phase * 1.4 + t * 1.3)
        wave /= 1.7
        return self._shape_amplitude(wave)

    def _spectrum_value(self, channel_index: int, pos_norm: float) -> float:
        amp = abs(self._channel_amplitude(channel_index, pos_norm))
        slope = max(0.2, 1.0 - pos_norm * 0.35)
        wobble = math.sin(self._anim_t * 1.2 + pos_norm * 7.0 + channel_index * 0.8) * 0.25 + 0.75
        shaped = amp * slope * wobble
        floor = 0.08
        return max(floor, min(1.0, shaped))

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor('#0d0f16'))
        c = self._canvas_rect()
        if self._pix and not self._pix.isNull():
            p.drawPixmap(c, self._pix.scaled(c.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        else:
            p.fillRect(c, QtGui.QColor('#1a1f2a'))

        wb = self._rect_to_widget(self._box)

        if self._bg_opacity > 0.01:
            p.fillRect(wb, QtGui.QColor(0, 0, 0, int(self._bg_opacity * 255)))

        pen = QtGui.QPen(self._color)
        pen.setColor(QtGui.QColor(self._color.red(), self._color.green(), self._color.blue(), int(self._alpha * 255)))
        p.setPen(pen)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        rows = self._channel_rows()
        row_rects = self._row_rects(wb, rows)

        if self._style == 'line':
            for idx, rrect in enumerate(row_rects):
                steps = max(64, max(1, rrect.width()) // 3)
                path = QtGui.QPainterPath()
                for i in range(steps + 1):
                    pos_norm = i / steps if steps else 0.0
                    amp = self._channel_amplitude(idx, pos_norm)
                    x = rrect.x() + int(pos_norm * rrect.width())
                    y = rrect.center().y() - amp * (rrect.height() * 0.45)
                    if i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                p.drawPath(path)
        elif self._style in ('sticks', 'rounded'):
            period = max(1, self._bar_px + self._gap_px)
            cols = max(1, min(400, (wb.width() + self._gap_px) // period))
            used_w = cols * self._bar_px + (cols - 1) * self._gap_px
            start_x = wb.x() + (wb.width() - used_w) // 2
            for idx, rrect in enumerate(row_rects):
                for i in range(cols):
                    pos_norm = i / max(1, cols - 1)
                    amp_val = self._channel_amplitude(idx, pos_norm)
                    amp_abs = min(1.0, abs(amp_val))
                    bar_h = max(2, int(amp_abs * rrect.height() * 0.95))
                    bar_h = min(rrect.height(), bar_h)
                    x = start_x + i * period
                    y = rrect.bottom() - bar_h
                    bar_rect = QtCore.QRect(x, y, self._bar_px, bar_h)
                    if self._style == 'rounded' and self._round_px > 0:
                        radius = min(self._round_px, min(bar_rect.width(), bar_rect.height()) // 2)
                        shape = QtGui.QPainterPath()
                        shape.addRoundedRect(QtCore.QRectF(bar_rect), radius, radius)
                        p.fillPath(shape, pen.color())
                    else:
                        p.fillRect(bar_rect, pen.color())
        else:
            period = max(1, self._bar_px + self._gap_px)
            cols = max(4, min(200, (wb.width() + self._gap_px) // period))
            used_w = cols * self._bar_px + (cols - 1) * self._gap_px
            start_x = wb.x() + (wb.width() - used_w) // 2
            for idx, rrect in enumerate(row_rects):
                for i in range(cols):
                    pos_norm = i / max(1, cols - 1)
                    amp_val = self._spectrum_value(idx, pos_norm)
                    bar_h = max(2, int(amp_val * rrect.height() * 0.95))
                    bar_h = min(rrect.height(), bar_h)
                    x = start_x + i * period
                    y = rrect.bottom() - bar_h
                    bar_rect = QtCore.QRect(x, y, self._bar_px, bar_h)
                    if self._round_px > 0:
                        radius = min(self._round_px, min(bar_rect.width(), bar_rect.height()) // 2)
                        shape = QtGui.QPainterPath()
                        shape.addRoundedRect(QtCore.QRectF(bar_rect), radius, radius)
                        p.fillPath(shape, pen.color())
                    else:
                        p.fillRect(bar_rect, pen.color())

        box_pen = QtGui.QPen(QtGui.QColor('#FFFFFF'), 1, QtCore.Qt.SolidLine)
        if self._split_channels and len(row_rects) > 1:
            divider_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 60), 1, QtCore.Qt.SolidLine)
            p.setPen(divider_pen)
            for rect in row_rects[:-1]:
                y = rect.bottom()
                p.drawLine(rect.left(), y, rect.right(), y)
        p.setPen(box_pen)
        p.drawRect(wb)
        for hp in self._handle_points(wb):
            handle_rect = QtCore.QRect(hp.x() - HANDLE_SIZE // 2, hp.y() - HANDLE_SIZE // 2, HANDLE_SIZE, HANDLE_SIZE)
            p.fillRect(handle_rect, QtGui.QColor('#FFFFFF'))

    def _handle_points(self, r: QtCore.QRect):
        return [
            QtCore.QPoint(r.left(), r.top()),
            QtCore.QPoint(r.center().x(), r.top()),
            QtCore.QPoint(r.right(), r.top()),
            QtCore.QPoint(r.left(), r.center().y()),
            QtCore.QPoint(r.right(), r.center().y()),
            QtCore.QPoint(r.left(), r.bottom()),
            QtCore.QPoint(r.center().x(), r.bottom()),
            QtCore.QPoint(r.right(), r.bottom()),
        ]

    def _hit_handle(self, pos: QtCore.QPoint, wr: QtCore.QRect):
        for i, pt in enumerate(self._handle_points(wr)):
            box = QtCore.QRect(pt.x()-HANDLE_SIZE//2, pt.y()-HANDLE_SIZE//2, HANDLE_SIZE, HANDLE_SIZE)
            if box.contains(pos): return i
        return None

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() != QtCore.Qt.LeftButton: return
        wr = self._rect_to_widget(self._box)
        h = self._hit_handle(e.pos(), wr)
        if h is not None:
            self._resizing = True; self._resize_handle = h; self._drag_origin = e.pos(); self._orig = QtCore.QRect(self._box)
        elif wr.contains(e.pos()):
            self._dragging = True; self._drag_origin = e.pos(); self._orig = QtCore.QRect(self._box)

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        wr = self._rect_to_widget(self._box)
        if self._dragging:
            dx = e.pos().x() - self._drag_origin.x(); dy = e.pos().y() - self._drag_origin.y()
            c = self._canvas_rect(); sx = self._video_w / max(1, c.width()); sy = self._video_h / max(1, c.height())
            nx = max(0, min(self._video_w - self._box.width(), self._orig.x() + int(dx*sx)))
            ny = max(0, min(self._video_h - self._box.height(), self._orig.y() + int(dy*sy)))
            self.setBox(nx, ny, self._box.width(), self._box.height())
        elif self._resizing and self._resize_handle is not None:
            c = self._canvas_rect(); sx = self._video_w / max(1, c.width()); sy = self._video_h / max(1, c.height())
            dx = int((e.pos().x() - self._drag_origin.x()) * sx); dy = int((e.pos().y() - self._drag_origin.y()) * sy)
            b = QtCore.QRect(self._orig)
            if self._resize_handle in (0,1,5,6): b.setTop(max(0, min(self._orig.bottom()-40, self._orig.top()+dy)))
            if self._resize_handle in (2,1,7,6): b.setRight(min(self._video_w, max(self._orig.left()+10, self._orig.right()+dx)))
            if self._resize_handle in (0,3,2,4): b.setLeft(max(0, min(self._orig.right()-10, self._orig.left()+dx)))
            if self._resize_handle in (5,6,7,4): b.setBottom(min(self._video_h, max(self._orig.top()+40, self._orig.bottom()+dy)))
            b = b.intersected(QtCore.QRect(0,0,self._video_w,self._video_h))
            self.setBox(b.x(), b.y(), b.width(), b.height())
        else:
            h = self._hit_handle(e.pos(), wr)
            if h is not None:
                cursors = {
                    0: QtCore.Qt.SizeFDiagCursor, 1: QtCore.Qt.SizeVerCursor, 2: QtCore.Qt.SizeBDiagCursor,
                    3: QtCore.Qt.SizeHorCursor, 4: QtCore.Qt.SizeHorCursor,
                    5: QtCore.Qt.SizeBDiagCursor, 6: QtCore.Qt.SizeVerCursor, 7: QtCore.Qt.SizeFDiagCursor
                }
                self.setCursor(cursors.get(h, QtCore.Qt.SizeAllCursor))
            elif wr.contains(e.pos()):
                self.setCursor(QtCore.Qt.SizeAllCursor)
            else:
                self.setCursor(QtCore.Qt.ArrowCursor)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        self._dragging = False; self._resizing = False; self._resize_handle = None
