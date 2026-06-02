# turborreactor-ignicion-telemetria
Sistema de ignición y telemetría para turborreactor — ESP32 DAQ + Dashboard PyQt5
#  Turborreactor — Sistema de Ignición y Telemetría

Sistema de adquisición de datos (DAQ) y dashboard de telemetría en tiempo real para el proyecto de turborreactor. Usa un ESP32 como unidad de control y una PC como estación de monitoreo.

---

## Archivos

| Archivo | Descripción |
|---|---|
| `Turborreactor_DAQ_ESP32.ino` | Firmware del ESP32: lee temperaturas con sensores MAX6675 y controla relés de gas e ignición |
| `dashboardPro.py` | Dashboard en Python: muestra temperaturas en tiempo real y envía comandos al ESP32 vía Serial |

---

## Requisitos

### ESP32 (Arduino IDE)
- [Arduino IDE](https://www.arduino.cc/en/software) con soporte para ESP32
- Librería `max6675` (instalar desde el Library Manager)

### Dashboard (PC)
- Python 3.8+
- Instalar dependencias:

```bash
pip install PyQt5 pyqtgraph pyserial
```

---

## Conexiones del ESP32

| Pin ESP32 | Función |
|---|---|
| 18 | SCK (MAX6675) |
| 19 | MISO (MAX6675) |
| 5 | CS — Sensor entrada |
| 17 | CS — Sensor salida |
| 26 | Relé válvula de gas |
| 27 | Relé generador de ignición HV |

---

## Uso

1. Cargar el `.ino` en el ESP32 con Arduino IDE
2. Conectar el ESP32 a la PC por USB
3. Correr el dashboard:

```bash
python dashboardPro.py
```

4. Seleccionar el puerto COM del ESP32 en el dashboard y conectar

---

## Comandos Serial (115200 baud)

| Comando | Acción |
|---|---|
| `STOP` | Parada de emergencia |
| `SPARK_ON` | Activa ignición |
| `SPARK_OFF` | Desactiva ignición |

Los datos de temperatura se reciben como `TEMP_IN,TEMP_OUT\n` (ej. `24.50,25.75`).
