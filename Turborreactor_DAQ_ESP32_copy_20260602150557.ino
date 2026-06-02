#include <Arduino.h>
#include <max6675.h>

// ==================== DEFINICIÓN DE PINES ====================
#define PIN_SCK     18
#define PIN_MISO    19
#define PIN_CS_IN   5
#define PIN_CS_OUT  17

#define PIN_RELAY_GAS        26   // Relé 1: Válvula butano
#define PIN_RELAY_IGNITION   27   // Relé 2: Generador HV (NUEVO)

// Lógica inversa del módulo de relé
#define RELAY_ON    LOW
#define RELAY_OFF   HIGH

#define READ_PERIOD_MS     250
#define SERIAL_PERIOD_MS   250
#define SERIAL_BAUDRATE    115200

MAX6675 thermo_in (PIN_SCK, PIN_CS_IN,  PIN_MISO);
MAX6675 thermo_out(PIN_SCK, PIN_CS_OUT, PIN_MISO);

SemaphoreHandle_t xTempMutex;
float g_tempIn  = 0.0f;
float g_tempOut = 0.0f;

volatile bool g_emergencyStop = false;
volatile bool g_sparkActive   = false;   // NUEVO: estado de ignición

TaskHandle_t hTaskCore0 = NULL;
TaskHandle_t hTaskCore1 = NULL;

// ====================================================================
//  NÚCLEO 0: Sensores + Control de Relés
// ====================================================================
void taskTempControl(void *pvParameters) {
  // Gas: abre válvula al arrancar (comportamiento original)
  digitalWrite(PIN_RELAY_GAS,      RELAY_ON);
  pinMode(PIN_RELAY_GAS,           OUTPUT);
  digitalWrite(PIN_RELAY_GAS,      RELAY_ON);

  // Ignición: apagada por defecto (seguridad)
  digitalWrite(PIN_RELAY_IGNITION, RELAY_OFF);
  pinMode(PIN_RELAY_IGNITION,      OUTPUT);
  digitalWrite(PIN_RELAY_IGNITION, RELAY_OFF);

  vTaskDelay(pdMS_TO_TICKS(500));
  TickType_t xLastWakeTime = xTaskGetTickCount();
  const TickType_t xPeriod = pdMS_TO_TICKS(READ_PERIOD_MS);

  for (;;) {
    float t_in  = thermo_in.readCelsius();
    float t_out = thermo_out.readCelsius();

    if (isnan(t_in))  t_in  = -999.0f;
    if (isnan(t_out)) t_out = -999.0f;

    if (xSemaphoreTake(xTempMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
      g_tempIn  = t_in;
      g_tempOut = t_out;
      xSemaphoreGive(xTempMutex);
    }

    // ── Control relé gas (lógica original) ──────────────────────────
    if (g_emergencyStop) {
      digitalWrite(PIN_RELAY_GAS, RELAY_OFF);
    } else {
      digitalWrite(PIN_RELAY_GAS, RELAY_ON);
    }

    // ── Control relé ignición (NUEVO) ────────────────────────────────
    // Si hay emergencia activa, la ignición se fuerza OFF sin importar
    // el estado de g_sparkActive
    if (g_emergencyStop || !g_sparkActive) {
      digitalWrite(PIN_RELAY_IGNITION, RELAY_OFF);
    } else {
      digitalWrite(PIN_RELAY_IGNITION, RELAY_ON);
    }

    vTaskDelayUntil(&xLastWakeTime, xPeriod);
  }
}

// ====================================================================
//  NÚCLEO 1: Envío Serial + Comandos
// ====================================================================
void taskSerialComm(void *pvParameters) {
  String inputBuffer = "";
  inputBuffer.reserve(32);
  TickType_t xLastWakeTime = xTaskGetTickCount();
  const TickType_t xPeriod = pdMS_TO_TICKS(SERIAL_PERIOD_MS);

  for (;;) {
    float t_in_local  = 0.0f;
    float t_out_local = 0.0f;

    if (xSemaphoreTake(xTempMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
      t_in_local  = g_tempIn;
      t_out_local = g_tempOut;
      xSemaphoreGive(xTempMutex);
    }

    Serial.print(t_in_local,  2);
    Serial.print(",");
    Serial.println(t_out_local, 2);

    while (Serial.available() > 0) {
      char c = (char)Serial.read();
      if (c == '\n' || c == '\r') {
        inputBuffer.trim();
        inputBuffer.toUpperCase();

        if (inputBuffer == "STOP") {
          g_emergencyStop = true;
          g_sparkActive   = false;   // Forzar ignición OFF en emergencia
          Serial.println(">>> ALERTA: Comando STOP recibido. CERRANDO VALVULA DE GAS <<<");
        }
        else if (inputBuffer == "SPARK_ON") {
          if (!g_emergencyStop) {
            g_sparkActive = true;
            Serial.println(">>> IGNICION: SPARK_ON recibido. Activando chispero <<<");
          }
        }
        else if (inputBuffer == "SPARK_OFF") {
          g_sparkActive = false;
          Serial.println(">>> IGNICION: SPARK_OFF recibido. Chispero apagado <<<");
        }

        inputBuffer = "";
      } else {
        if (inputBuffer.length() < 30) inputBuffer += c;
      }
    }

    vTaskDelayUntil(&xLastWakeTime, xPeriod);
  }
}

// ====================================================================
//  SETUP
// ====================================================================
void setup() {
  Serial.begin(SERIAL_BAUDRATE);
  delay(300);
  xTempMutex = xSemaphoreCreateMutex();

  xTaskCreatePinnedToCore(taskTempControl, "TempControl", 4096, NULL, 2, &hTaskCore0, 0);
  delay(100);
  xTaskCreatePinnedToCore(taskSerialComm, "SerialComm",  4096, NULL, 1, &hTaskCore1, 1);
}

void loop() {
  vTaskDelay(portMAX_DELAY);
}