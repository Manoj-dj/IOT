/**
 * ╔══════════════════════════════════════════════════════════════════════════╗
 * ║          Smart-Manhole ESP32 — Real Hardware → Live Dashboard           ║
 * ╠══════════════════════════════════════════════════════════════════════════╣
 * ║  Sensors  : DHT22 (GPIO 4), HC-SR04 (TRIG:5, ECHO:18), MQ Gas (GPIO 34)║
 * ║  Actuators: Buzzer (GPIO 26), LED (GPIO 2)                              ║
 * ║  Protocol : HTTP POST → FastAPI /api/wokwi endpoint every 3 seconds     ║
 * ╠══════════════════════════════════════════════════════════════════════════╣
 * ║  THRESHOLD LEVELS (matching dashboard)                                  ║
 * ║  Gas → methane ppm (mapped from ADC 0-4095 → 0-2000 ppm):              ║
 * ║    SAFE:    < 500 ppm   (ADC < ~1024)                                   ║
 * ║    WARNING: 500–999 ppm (ADC 1024–2047)                                 ║
 * ║    DANGER:  ≥ 1000 ppm  (ADC ≥ 2048)                                   ║
 * ║  Water level (inverted distance cm):                                    ║
 * ║    SAFE:    < 55 cm   (distance > 45 cm from sensor)                   ║
 * ║    WARNING: 55–74 cm  (distance 26–45 cm from sensor)                  ║
 * ║    DANGER:  ≥ 75 cm   (distance ≤ 25 cm from sensor)                   ║
 * ║  Temperature:  WARNING ≥ 40°C  |  DANGER ≥ 50°C                        ║
 * ║  Humidity:     WARNING ≥ 78%   |  DANGER ≥ 90%                         ║
 * ╠══════════════════════════════════════════════════════════════════════════╣
 * ║  WIRING SUMMARY                                                         ║
 * ║  DHT22   → VCC:3.3V  GND  DATA:GPIO4  (10kΩ pull-up DATA→3.3V)        ║
 * ║  HC-SR04 → VCC:5V    GND  TRIG:GPIO5  ECHO:GPIO18(voltage divider!)    ║
 * ║  MQ Gas  → VCC:5V    GND  AOUT:GPIO34 (ADC-only, input only)           ║
 * ║  Buzzer  → + :GPIO26  –:GND                                             ║
 * ║  LED     → + :GPIO2(220Ω) –:GND                                         ║
 * ╠══════════════════════════════════════════════════════════════════════════╣
 * ║  SETUP STEPS                                                            ║
 * ║  1. Install libraries in Arduino IDE:                                   ║
 * ║     • "DHT sensor library" by Adafruit                                  ║
 * ║     • "Adafruit Unified Sensor" by Adafruit                             ║
 * ║  2. Set your WiFi SSID & Password below                                 ║
 * ║  3. Set SERVER_IP to your PC's local IPv4 (run `ipconfig` in CMD)       ║
 * ║  4. Start FastAPI: uvicorn main:app --host 0.0.0.0 --port 8000          ║
 * ║  5. Upload to ESP32 → open Serial Monitor at 115200 baud                ║
 * ╚══════════════════════════════════════════════════════════════════════════╝
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

// ╔═══════════════════════════════════════════╗
// ║  ⚙️  USER CONFIGURATION — CHANGE THESE   ║
// ╚═══════════════════════════════════════════╝

// Your home/office WiFi credentials
const char* WIFI_SSID     = "YOUR_WIFI_SSID";       // <-- Change this
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";    // <-- Change this

// Your PC's local IP address where FastAPI is running
// Run  ipconfig  in CMD and look for "IPv4 Address"
const char* SERVER_IP   = "192.168.1.100";           // <-- Change this
const int   SERVER_PORT = 8000;

// Manhole ID to identify which manhole this ESP32 belongs to
const char* MANHOLE_ID  = "MH-001";

// How often to send data (milliseconds)
const unsigned long SEND_INTERVAL_MS = 3000;

// ╔═══════════════════════════════════════════╗
// ║  📌  PIN DEFINITIONS                      ║
// ╚═══════════════════════════════════════════╝

#define DHTPIN    4       // DHT22 data pin
#define DHTTYPE   DHT22   // Use DHT11 if you have the blue one

#define GAS_PIN   34      // MQ gas sensor analog output (ADC-capable pin)
                          // GPIO34 is input-only on ESP32 — perfect for ADC

#define TRIG_PIN  5       // HC-SR04 trigger
#define ECHO_PIN  18      // HC-SR04 echo  (MUST use voltage divider! 1kΩ+2kΩ)

#define BUZZER_PIN 26     // Active buzzer positive
#define LED_PIN    2      // LED (onboard LED on most ESP32 dev boards)

// ╔═══════════════════════════════════════════╗
// ║  ⚡  DASHBOARD THRESHOLDS (ppm / cm / °)  ║
// ╚═══════════════════════════════════════════╝

// Gas / Methane (ADC 0-4095 maps to 0-2000 ppm on dashboard)
// ADC raw thresholds derived from:  adc = (ppm / 2000) * 4095
const int GAS_ADC_WARNING = 1024;   // ~500 ppm warning threshold
const int GAS_ADC_DANGER  = 2048;   // ~1000 ppm danger threshold

// Water level (cm) — dashboard uses  water_level = 100 - distance
// If distance sensor is 45cm from water surface → water_level = 55cm (WARNING)
// If distance sensor is 25cm from water surface → water_level = 75cm (DANGER)
const float DIST_WARNING_CM = 45.0;  // water_level = 55 cm → WARNING
const float DIST_DANGER_CM  = 25.0;  // water_level = 75 cm → DANGER

// Temperature (°C)
const float TEMP_WARNING = 40.0;
const float TEMP_DANGER  = 50.0;

// Humidity (%)
const float HUM_WARNING  = 78.0;
const float HUM_DANGER   = 90.0;

// Maximum distance reading in cm (treat > this as "no reading")
const float MAX_DISTANCE_CM = 400.0;

// ═══════════════════════════════════════════════════════════════════════════

DHT dht(DHTPIN, DHTTYPE);
unsigned long lastSendTime = 0;

// ── Alert state tracking (for buzzer/LED patterns) ──────────────────────────
enum AlertLevel { SAFE, WARNING, DANGER };
AlertLevel currentLevel = SAFE;

// ── HC-SR04: measure distance in cm ─────────────────────────────────────────
float getDistance() {
  // Send 10µs HIGH pulse to trigger
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Measure echo pulse width (timeout = 30ms → max ~5m)
  long duration = pulseIn(ECHO_PIN, HIGH, 30000UL);

  if (duration == 0) {
    return 0.0;  // No echo = sensor not responding / too far
  }
  // Speed of sound: 0.034 cm/µs  →  distance = (duration / 2) × 0.034
  float dist = (duration / 2.0f) * 0.034f;
  return (dist > MAX_DISTANCE_CM) ? 0.0 : dist;
}

// ── WiFi connection ──────────────────────────────────────────────────────────
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("\n🔌 Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi Connected!");
    Serial.print("   IP Address : "); Serial.println(WiFi.localIP());
    Serial.print("   Signal RSSI: "); Serial.print(WiFi.RSSI()); Serial.println(" dBm");
    Serial.print("   Server     : http://"); Serial.print(SERVER_IP);
    Serial.print(":"); Serial.println(SERVER_PORT);
  } else {
    Serial.println("\n❌ WiFi FAILED! Check SSID/Password. Retrying next cycle...");
  }
}

// ── Determine alert level from sensor readings ────────────────────────────────
AlertLevel classifyLevel(int gasADC, float tempC, float humPct, float distCm) {
  bool isDanger  = false;
  bool isWarning = false;

  // Gas check
  if (gasADC >= GAS_ADC_DANGER)       isDanger  = true;
  else if (gasADC >= GAS_ADC_WARNING) isWarning = true;

  // Water level check (lower distance = higher water level)
  if (distCm > 0 && distCm <= DIST_DANGER_CM)       isDanger  = true;
  else if (distCm > 0 && distCm <= DIST_WARNING_CM) isWarning = true;

  // Temperature check
  if (tempC >= TEMP_DANGER)       isDanger  = true;
  else if (tempC >= TEMP_WARNING) isWarning = true;

  // Humidity check
  if (humPct >= HUM_DANGER)       isDanger  = true;
  else if (humPct >= HUM_WARNING) isWarning = true;

  if (isDanger)  return DANGER;
  if (isWarning) return WARNING;
  return SAFE;
}

// ── Drive buzzer and LED based on alert level ────────────────────────────────
void driveActuators(AlertLevel level) {
  static unsigned long lastBeepTime = 0;
  static bool buzzerState = false;
  unsigned long now = millis();

  switch (level) {
    case DANGER:
      // Rapid continuous beep: on/off every 200 ms
      if (now - lastBeepTime >= 200) {
        buzzerState = !buzzerState;
        digitalWrite(BUZZER_PIN, buzzerState ? HIGH : LOW);
        digitalWrite(LED_PIN,    buzzerState ? HIGH : LOW);
        lastBeepTime = now;
      }
      break;

    case WARNING:
      // Slow beep: on/off every 800 ms
      if (now - lastBeepTime >= 800) {
        buzzerState = !buzzerState;
        digitalWrite(BUZZER_PIN, buzzerState ? HIGH : LOW);
        // LED stays ON at WARNING, just buzzer pulses
        digitalWrite(LED_PIN, HIGH);
        lastBeepTime = now;
      }
      break;

    case SAFE:
    default:
      // Silent, LED off
      digitalWrite(BUZZER_PIN, LOW);
      digitalWrite(LED_PIN,    LOW);
      buzzerState = false;
      break;
  }
}

// ── Print sensor readings to Serial Monitor ───────────────────────────────────
void printReadings(int gasADC, float tempC, float humPct, float distCm,
                   float methanePPM, float waterLevel, AlertLevel level) {
  Serial.println("\n┌─────────────────────────────────────┐");
  Serial.println("│        SMART-MANHOLE READINGS        │");
  Serial.println("├─────────────────────────────────────┤");
  Serial.print("│ Gas ADC     : "); Serial.print(gasADC);
  Serial.print("  (≈ "); Serial.print(methanePPM, 0); Serial.println(" ppm methane)   │");
  Serial.print("│ Temperature : "); Serial.print(tempC, 1); Serial.println(" °C                     │");
  Serial.print("│ Humidity    : "); Serial.print(humPct, 1); Serial.println(" %                      │");
  Serial.print("│ Distance    : "); Serial.print(distCm, 1); Serial.println(" cm from sensor         │");
  Serial.print("│ Water Level : "); Serial.print(waterLevel, 1); Serial.println(" cm (dashboard value)   │");
  Serial.println("├─────────────────────────────────────┤");
  Serial.print("│ Status      : ");
  switch (level) {
    case DANGER:  Serial.println("🔴 DANGER  ← HAZARDOUS!            │"); break;
    case WARNING: Serial.println("🟡 WARNING ← Monitor closely!      │"); break;
    case SAFE:    Serial.println("🟢 SAFE    ← All within limits!    │"); break;
  }
  Serial.println("└─────────────────────────────────────┘");
}

// ── Send data to FastAPI server ───────────────────────────────────────────────
bool sendToServer(int gasADC, float tempC, float humPct, float distCm,
                  AlertLevel level) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("📵 No WiFi — skipping HTTP POST");
    return false;
  }

  HTTPClient http;
  String url = "http://" + String(SERVER_IP) + ":" + String(SERVER_PORT) + "/api/wokwi";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);  // 5 second timeout

  int buzzerFlag = (level == DANGER || level == WARNING) ? 1 : 0;
  int ledFlag    = (level == DANGER) ? 1 : 0;

  // Build JSON manually (avoids ArduinoJson dependency)
  String body = "{";
  body += "\"gas\":"         + String(gasADC)        + ",";
  body += "\"temperature\":" + String(tempC, 2)      + ",";
  body += "\"humidity\":"    + String(humPct, 2)     + ",";
  body += "\"distance\":"    + String(distCm, 2)     + ",";
  body += "\"buzzer\":"      + String(buzzerFlag)    + ",";
  body += "\"led\":"         + String(ledFlag)       + ",";
  body += "\"manhole_id\":\"" + String(MANHOLE_ID) + "\"";
  body += "}";

  Serial.print("📡 POST → "); Serial.println(url);
  Serial.print("   Body: "); Serial.println(body);

  int httpCode = http.POST(body);
  http.end();

  if (httpCode == 200) {
    Serial.println("   ✅ Dashboard updated (HTTP 200 OK)");
    return true;
  } else {
    Serial.print("   ⚠️  HTTP Error: "); Serial.println(httpCode);
    if (httpCode < 0) {
      Serial.println("   🔴 Connection refused — is the server running?");
      Serial.print("   📍 URL was: "); Serial.println(url);
    }
    return false;
  }
}

// ════════════════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n╔═══════════════════════════════════════╗");
  Serial.println("║    Smart-Manhole ESP32 v2.0           ║");
  Serial.println("║    Sensors → FastAPI Dashboard        ║");
  Serial.println("╚═══════════════════════════════════════╝");

  // Pin modes
  pinMode(TRIG_PIN,  OUTPUT);
  pinMode(ECHO_PIN,  INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN,   OUTPUT);

  // Startup blink to confirm board is alive
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_PIN, HIGH); delay(150);
    digitalWrite(LED_PIN, LOW);  delay(150);
  }

  dht.begin();
  delay(2000);  // DHT22 needs 2s after power-on before first reading

  connectWiFi();

  Serial.println("\n📊 Thresholds loaded from dashboard:");
  Serial.print("   Gas   → WARNING: "); Serial.print(GAS_ADC_WARNING);
  Serial.print(" ADC (~500 ppm)  |  DANGER: "); Serial.print(GAS_ADC_DANGER); Serial.println(" ADC (~1000 ppm)");
  Serial.print("   Water → WARNING: dist ≤ "); Serial.print(DIST_WARNING_CM);
  Serial.print(" cm  |  DANGER: dist ≤ "); Serial.print(DIST_DANGER_CM); Serial.println(" cm");
  Serial.print("   Temp  → WARNING: ≥ "); Serial.print(TEMP_WARNING);
  Serial.print("°C  |  DANGER: ≥ "); Serial.print(TEMP_DANGER); Serial.println("°C");
  Serial.print("   Hum   → WARNING: ≥ "); Serial.print(HUM_WARNING);
  Serial.print("%   |  DANGER: ≥ "); Serial.print(HUM_DANGER); Serial.println("%");
  Serial.println("\n🚀 Starting sensor loop...\n");
}

// ════════════════════════════════════════════════════════════════════════════
//  MAIN LOOP
// ════════════════════════════════════════════════════════════════════════════
void loop() {
  unsigned long now = millis();

  // ── 1. Keep buzzer/LED actuating according to current alert level ──────
  driveActuators(currentLevel);

  // ── 2. Re-check WiFi every loop (non-blocking) ─────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  // ── 3. Read + send every SEND_INTERVAL_MS ────────────────────────────────
  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    // ── READ SENSORS ─────────────────────────────────────────────────────

    // Gas sensor (ADC 0–4095; ESP32 ADC is 12-bit)
    // Average 5 readings to reduce noise
    long gasSum = 0;
    for (int i = 0; i < 5; i++) {
      gasSum += analogRead(GAS_PIN);
      delay(5);
    }
    int gasADC = (int)(gasSum / 5);

    // DHT22 — temperature & humidity
    float tempC  = dht.readTemperature();
    float humPct = dht.readHumidity();

    // Guard against failed DHT reads (returns NaN)
    if (isnan(tempC)  || tempC  < -40.0 || tempC  > 80.0) tempC  = 25.0;
    if (isnan(humPct) || humPct < 0.0   || humPct > 100.0) humPct = 50.0;

    // HC-SR04 — distance to water surface in cm
    float distCm = getDistance();

    // ── CONVERSIONS (matching server-side _build_wokwi_entry logic) ──────
    // methane ppm = (gasADC / 4095) * 2000
    float methanePPM = (gasADC / 4095.0f) * 2000.0f;

    // water_level on dashboard = 100 - distance  (higher water = higher level)
    float waterLevel = (distCm > 0 && distCm <= 100.0) ? (100.0f - distCm) : 0.0f;

    // ── CLASSIFY ALERT LEVEL (matches dashboard thresholds exactly) ──────
    currentLevel = classifyLevel(gasADC, tempC, humPct, distCm);

    // ── SERIAL OUTPUT ────────────────────────────────────────────────────
    printReadings(gasADC, tempC, humPct, distCm, methanePPM, waterLevel, currentLevel);

    // ── SEND TO FASTAPI DASHBOARD ─────────────────────────────────────────
    sendToServer(gasADC, tempC, humPct, distCm, currentLevel);
  }

  // Small delay to avoid watchdog reset (actuator loop still runs fast)
  delay(10);
}
