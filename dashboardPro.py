"""
================================================================
  AEROSPACE TELEMETRY DASHBOARD  //  ESP32 LINK  //  v2.0
================================================================
  Real-time telemetry dashboard for ESP32 thermal sensors.
  Protocol: ASCII over Serial @ 115200 baud
  Frame:    "TEMP_IN,TEMP_OUT\n"   (e.g.  "24.50,25.75")
  Cmd OUT:  "STOP\n"               (emergency kill)
  Cmd OUT:  "SPARK_ON\n"           (hold-to-ignite)
  Cmd OUT:  "SPARK_OFF\n"          (release to cut spark)
================================================================
"""

import sys
from collections import deque

from PyQt5.QtCore import QThread, pyqtSignal, QMutex, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFrame, QMessageBox
)
import pyqtgraph as pg
import serial
import serial.tools.list_ports


# ────────────────────────────────────────────────────────────────
#  VISUAL DESIGN TOKENS
# ────────────────────────────────────────────────────────────────
MAX_POINTS       = 200

COLOR_BG         = "#0A0E1A"
COLOR_PANEL      = "#131825"
COLOR_BORDER     = "#1F2937"
COLOR_TEXT       = "#E5E7EB"
COLOR_TEXT_DIM   = "#6B7280"
COLOR_ACCENT     = "#3B82F6"
COLOR_SUCCESS    = "#10B981"
COLOR_DANGER     = "#DC2626"
COLOR_DANGER_HOV = "#EF4444"

COLOR_TEMP_IN    = "#00D9FF"
COLOR_TEMP_OUT   = "#FF6B35"

# NUEVO — tokens de ignición
COLOR_SPARK      = "#FFD700"
COLOR_SPARK_BG   = "#1A1400"
COLOR_SPARK_ACT  = "#000000"   # texto cuando está activo (fondo amarillo)


# ════════════════════════════════════════════════════════════════
#  SERIAL READER  —  background QThread  (sin cambios)
# ════════════════════════════════════════════════════════════════
class SerialReader(QThread):
    data_received     = pyqtSignal(float, float)
    connection_error  = pyqtSignal(str)
    status_changed    = pyqtSignal(bool)

    def __init__(self, port: str, baudrate: int, parent=None):
        super().__init__(parent)
        self.port      = port
        self.baudrate  = baudrate
        self._serial   = None
        self._running  = False
        self._mutex    = QMutex()

    def run(self):
        try:
            self._serial  = serial.Serial(self.port, self.baudrate, timeout=1)
            self._running = True
            self.status_changed.emit(True)
        except (serial.SerialException, OSError) as e:
            self.connection_error.emit(f"No se pudo abrir {self.port}\n\n{e}")
            return

        while self._running:
            try:
                if self._serial.in_waiting > 0:
                    raw  = self._serial.readline()
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) == 2:
                        try:
                            self.data_received.emit(float(parts[0]),
                                                    float(parts[1]))
                        except ValueError:
                            pass
                else:
                    self.msleep(5)
            except (serial.SerialException, OSError) as e:
                self.connection_error.emit(f"Error de lectura: {e}")
                break

        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self.status_changed.emit(False)

    def stop(self):
        self._running = False
        self.wait(2000)

    def send_command(self, command: str) -> bool:
        self._mutex.lock()
        try:
            if self._serial and self._serial.is_open:
                self._serial.write(command.encode("utf-8"))
                self._serial.flush()
                return True
            return False
        except Exception:
            return False
        finally:
            self._mutex.unlock()


# ════════════════════════════════════════════════════════════════
#  TEMPERATURE READOUT  (sin cambios)
# ════════════════════════════════════════════════════════════════
class TempDisplay(QFrame):
    def __init__(self, label_text: str, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.setObjectName("tempDisplay")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 18, 25, 18)
        layout.setSpacing(2)

        header = QLabel(label_text)
        header.setAlignment(Qt.AlignCenter)
        header_font = QFont("Consolas", 13, QFont.Bold)
        header_font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        header.setFont(header_font)
        header.setStyleSheet(f"color: {COLOR_TEXT_DIM};")

        self.value_label = QLabel("--.--")
        self.value_label.setAlignment(Qt.AlignCenter)
        value_font = QFont("Consolas", 84, QFont.Bold)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet(
            f"color: {color}; background: transparent;"
        )

        unit = QLabel("DEG  CELSIUS")
        unit.setAlignment(Qt.AlignCenter)
        unit_font = QFont("Consolas", 11, QFont.Bold)
        unit_font.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        unit.setFont(unit_font)
        unit.setStyleSheet(f"color: {color};")

        layout.addWidget(header)
        layout.addStretch(1)
        layout.addWidget(self.value_label)
        layout.addStretch(1)
        layout.addWidget(unit)

    def update_value(self, value: float):
        self.value_label.setText(f"{value:6.2f}")

    def reset(self):
        self.value_label.setText("--.--")


# ════════════════════════════════════════════════════════════════
#  IGNITION BUTTON  —  NUEVO
#  Hold-to-activate: emite spark_on al presionar, spark_off al soltar.
#  Usa señales para no acoplar directamente al serial_thread.
# ════════════════════════════════════════════════════════════════
class IgnitionButton(QPushButton):
    spark_on  = pyqtSignal()
    spark_off = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._firing = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self._firing = True
            self.spark_on.emit()
            self._refresh_style(active=True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._firing:
            self._firing = False
            self.spark_off.emit()
            self._refresh_style(active=False)
        super().mouseReleaseEvent(event)

    def reset(self):
        """Fuerza el estado visual a reposo (usar en emergencia o desconexión)."""
        self._firing = False
        self._refresh_style(active=False)

    def _refresh_style(self, active: bool):
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# ════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ════════════════════════════════════════════════════════════════
class MissionControl(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AEROSPACE TELEMETRY  //  ESP32 LINK  //  v2.0")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 750)

        self.serial_thread = None
        self.connected     = False

        self.buf_in  = deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
        self.buf_out = deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
        self.x_axis  = list(range(MAX_POINTS))

        self._build_ui()
        self._apply_stylesheet()
        self._refresh_ports()

    # ---- UI assembly --------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(12)

        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_displays(),   stretch=3)
        root.addWidget(self._build_plot_panel(), stretch=4)
        root.addWidget(self._build_kill_panel())

    # ······ top bar  (sin cambios) ··································
    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(64)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 20, 10)
        h.setSpacing(12)

        title_font = QFont("Consolas", 15, QFont.Bold)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 5)
        title = QLabel("◉  MISSION  CONTROL")
        title.setFont(title_font)
        title.setStyleSheet(f"color: {COLOR_ACCENT};")

        port_lbl = QLabel("PORT")
        port_lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-weight: bold;")
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)

        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setFixedSize(36, 32)
        self.refresh_btn.setToolTip("Refrescar lista de puertos")
        self.refresh_btn.clicked.connect(self._refresh_ports)

        baud_lbl = QLabel("BAUD")
        baud_lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-weight: bold;")
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200"])
        self.baud_combo.setMinimumWidth(110)
        self.baud_combo.setEnabled(False)

        self.status_dot  = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 22px;")
        self.status_text = QLabel("OFFLINE")
        st_font = QFont("Consolas", 11, QFont.Bold)
        st_font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        self.status_text.setFont(st_font)
        self.status_text.setStyleSheet(f"color: {COLOR_TEXT_DIM};")

        self.connect_btn = QPushButton("CONNECT")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.setMinimumWidth(150)
        self.connect_btn.clicked.connect(self._toggle_connection)

        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(port_lbl);   h.addWidget(self.port_combo)
        h.addWidget(self.refresh_btn)
        h.addSpacing(20)
        h.addWidget(baud_lbl);   h.addWidget(self.baud_combo)
        h.addSpacing(25)
        h.addWidget(self.status_dot); h.addWidget(self.status_text)
        h.addSpacing(15)
        h.addWidget(self.connect_btn)
        return bar

    # ······ displays  (sin cambios) ·································
    def _build_displays(self) -> QFrame:
        frame = QFrame()
        h = QHBoxLayout(frame)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(15)

        self.temp_in_display  = TempDisplay("TEMP  //  IN",  COLOR_TEMP_IN)
        self.temp_out_display = TempDisplay("TEMP  //  OUT", COLOR_TEMP_OUT)

        h.addWidget(self.temp_in_display)
        h.addWidget(self.temp_out_display)
        return frame

    # ······ plot  (sin cambios) ·····································
    def _build_plot_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("plotFrame")
        v = QVBoxLayout(frame)
        v.setContentsMargins(15, 12, 15, 12)
        v.setSpacing(8)

        hdr_font = QFont("Consolas", 11, QFont.Bold)
        hdr_font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        header = QLabel("▸  TEMPERATURE  TELEMETRY  //  LIVE  STREAM")
        header.setFont(hdr_font)
        header.setStyleSheet(f"color: {COLOR_TEXT_DIM};")

        pg.setConfigOptions(antialias=True, useOpenGL=False)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(COLOR_PANEL)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setLabel("left",   "Temperature (°C)",
                                  color=COLOR_TEXT_DIM, **{"font-size": "10pt"})
        self.plot_widget.setLabel("bottom", "Samples (last 200)",
                                  color=COLOR_TEXT_DIM, **{"font-size": "10pt"})

        for ax_name in ("left", "bottom"):
            ax = self.plot_widget.getAxis(ax_name)
            ax.setPen(pg.mkPen(COLOR_BORDER, width=1))
            ax.setTextPen(pg.mkPen(COLOR_TEXT))

        legend = self.plot_widget.addLegend(offset=(15, 10),
                                            labelTextColor=COLOR_TEXT)
        legend.setBrush(pg.mkBrush(10, 14, 26, 220))
        legend.setPen(pg.mkPen(COLOR_BORDER))

        pen_in  = pg.mkPen(color=COLOR_TEMP_IN,  width=2)
        pen_out = pg.mkPen(color=COLOR_TEMP_OUT, width=2)
        self.curve_in  = self.plot_widget.plot(self.x_axis, list(self.buf_in),
                                               pen=pen_in,  name="TEMP_IN")
        self.curve_out = self.plot_widget.plot(self.x_axis, list(self.buf_out),
                                               pen=pen_out, name="TEMP_OUT")
        v.addWidget(header)
        v.addWidget(self.plot_widget)
        return frame

    # ······ kill panel  — MODIFICADO: se agrega botón de ignición ···
    def _build_kill_panel(self) -> QFrame:
        frame = QFrame()
        h = QHBoxLayout(frame)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        # ── Botón de ignición (NUEVO) ────────────────────────────────
        self.ignition_btn = IgnitionButton(
            "   HOLD  TO  IGNITE   ( SPARK )   "
        )
        self.ignition_btn.setObjectName("ignitionBtn")
        self.ignition_btn.setFixedHeight(95)
        ignition_font = QFont("Consolas", 18, QFont.Bold)
        ignition_font.setLetterSpacing(QFont.AbsoluteSpacing, 5)
        self.ignition_btn.setFont(ignition_font)
        self.ignition_btn.setEnabled(False)

        # Conectar señales al serial_thread a través de lambdas
        self.ignition_btn.spark_on.connect(
            lambda: self.serial_thread and
                    self.serial_thread.send_command("SPARK_ON\n")
        )
        self.ignition_btn.spark_off.connect(
            lambda: self.serial_thread and
                    self.serial_thread.send_command("SPARK_OFF\n")
        )

        # ── Emergency Kill Switch (sin cambios internos) ─────────────
        self.kill_btn = QPushButton(
            "⚠   EMERGENCY  KILL  SWITCH   (STOP)   ⚠"
        )
        self.kill_btn.setObjectName("killBtn")
        self.kill_btn.setFixedHeight(95)
        kill_font = QFont("Consolas", 22, QFont.Bold)
        kill_font.setLetterSpacing(QFont.AbsoluteSpacing, 8)
        self.kill_btn.setFont(kill_font)
        self.kill_btn.setEnabled(False)
        self.kill_btn.clicked.connect(self._emergency_stop)

        h.addWidget(self.ignition_btn, stretch=1)
        h.addWidget(self.kill_btn,     stretch=1)
        return frame

    # ---- styling ------------------------------------------------------------
    def _apply_stylesheet(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT};
                font-family: 'Consolas', 'Courier New', monospace;
            }}
            QFrame#topBar, QFrame#tempDisplay, QFrame#plotFrame {{
                background-color: {COLOR_PANEL};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QComboBox {{
                background-color: {COLOR_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 6px 12px;
                color: {COLOR_TEXT};
                font-size: 12px;
            }}
            QComboBox:hover      {{ border: 1px solid {COLOR_ACCENT}; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{
                background-color: {COLOR_PANEL};
                color: {COLOR_TEXT};
                selection-background-color: {COLOR_ACCENT};
                border: 1px solid {COLOR_BORDER};
                outline: 0;
            }}
            QPushButton {{
                background-color: {COLOR_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 6px 14px;
                color: {COLOR_TEXT};
                font-weight: bold;
            }}
            QPushButton:hover {{
                border: 1px solid {COLOR_ACCENT};
                color: {COLOR_ACCENT};
            }}
            QPushButton#connectBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
            }}
            QPushButton#connectBtn:hover {{ background-color: #2563EB; }}
            QPushButton#connectBtn[connected="true"]       {{ background-color: {COLOR_SUCCESS}; }}
            QPushButton#connectBtn[connected="true"]:hover {{ background-color: #059669; }}

            QPushButton#killBtn {{
                background-color: {COLOR_DANGER};
                color: white;
                border: 4px solid #7F1D1D;
                border-radius: 10px;
            }}
            QPushButton#killBtn:hover:enabled   {{ background-color: {COLOR_DANGER_HOV}; border: 4px solid {COLOR_DANGER}; }}
            QPushButton#killBtn:pressed:enabled {{ background-color: #991B1B; }}
            QPushButton#killBtn:disabled {{
                background-color: #3F1414;
                color: #6B7280;
                border: 4px solid #2D0A0A;
            }}

            /* ── Ignition button — reposo ── */
            QPushButton#ignitionBtn {{
                background-color: {COLOR_SPARK_BG};
                color:            {COLOR_SPARK};
                border:           4px solid {COLOR_SPARK};
                border-radius:    10px;
            }}
            QPushButton#ignitionBtn:hover:enabled {{
                background-color: #2E2400;
                border-color:     #FFE44D;
            }}
            /* ── Ignition button — activo (chispa en curso) ── */
            QPushButton#ignitionBtn[active="true"] {{
                background-color: {COLOR_SPARK};
                color:            {COLOR_SPARK_ACT};
                border:           4px solid white;
            }}
            QPushButton#ignitionBtn:disabled {{
                background-color: #0F0D00;
                color:            #4A3F00;
                border:           4px solid #2E2800;
            }}

            QToolTip {{
                background-color: {COLOR_PANEL};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                padding: 4px;
            }}
        """)

    # ────────────────────────────────────────────────────────────
    #  CONTROLLER LOGIC  (sin cambios excepto lo marcado)
    # ────────────────────────────────────────────────────────────
    def _refresh_ports(self):
        previous = self.port_combo.currentData()
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()

        if not ports:
            self.port_combo.addItem("— NO PORTS DETECTED —", None)
            self.port_combo.setEnabled(False)
            self.connect_btn.setEnabled(False)
            return

        self.port_combo.setEnabled(True)
        self.connect_btn.setEnabled(True)
        for p in ports:
            self.port_combo.addItem(f"{p.device}  —  {p.description}", p.device)

        if previous:
            idx = self.port_combo.findData(previous)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def _toggle_connection(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Sin puerto",
                                "Selecciona un puerto COM válido.")
            return
        baud = int(self.baud_combo.currentText())

        self.serial_thread = SerialReader(port, baud)
        self.serial_thread.data_received.connect(self._on_data)
        self.serial_thread.connection_error.connect(self._on_error)
        self.serial_thread.status_changed.connect(self._on_status_changed)
        self.serial_thread.start()

    def _disconnect(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None

    def _on_status_changed(self, is_connected: bool):
        self.connected = is_connected
        if is_connected:
            self.connect_btn.setText("DISCONNECT")
            self.connect_btn.setProperty("connected", "true")
            self.status_dot.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 22px;")
            self.status_text.setText("LINK  ACTIVE")
            self.status_text.setStyleSheet(f"color: {COLOR_SUCCESS};")
            self.kill_btn.setEnabled(True)
            self.ignition_btn.setEnabled(True)   # NUEVO
            self.port_combo.setEnabled(False)
            self.refresh_btn.setEnabled(False)
        else:
            self.connect_btn.setText("CONNECT")
            self.connect_btn.setProperty("connected", "false")
            self.status_dot.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 22px;")
            self.status_text.setText("OFFLINE")
            self.status_text.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
            self.kill_btn.setEnabled(False)
            self.ignition_btn.setEnabled(False)  # NUEVO
            self.ignition_btn.reset()            # NUEVO — limpia visual
            self.port_combo.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.temp_in_display.reset()
            self.temp_out_display.reset()

        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)

    def _on_data(self, t_in: float, t_out: float):
        self.temp_in_display.update_value(t_in)
        self.temp_out_display.update_value(t_out)
        self.buf_in.append(t_in)
        self.buf_out.append(t_out)
        self.curve_in.setData(self.x_axis,  list(self.buf_in))
        self.curve_out.setData(self.x_axis, list(self.buf_out))

    def _on_error(self, message: str):
        QMessageBox.critical(self, "Error de Conexión", message)
        self._on_status_changed(False)

    def _emergency_stop(self):
        if not self.serial_thread:
            return
        self.ignition_btn.reset()                # NUEVO — corta chispa visualmente
        ok = self.serial_thread.send_command("STOP\n")
        if ok:
            QMessageBox.information(self, "EMERGENCY STOP",
                                    "✅ Comando STOP enviado al ESP32.")
        else:
            QMessageBox.warning(self, "EMERGENCY STOP",
                                "⚠ No se pudo enviar el comando: el puerto no está abierto.")

    def closeEvent(self, event):
        if self.serial_thread:
            self.serial_thread.stop()
        event.accept()


# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MissionControl()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()