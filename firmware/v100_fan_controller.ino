#include <Arduino.h>
#include <ESP8266WiFi.h>

// SXM2-to-PCIe adapter 4-wire blower controller for ESP8266 dev boards.
//
// D1 / GPIO5 -> 2.2k -> NPN base
// NPN emitter -> common GND
// NPN collector -> fan PWM
// D2 / GPIO4 <- 2.2k <- fan TACH, external 10k pull-up to ESP 3.3V
//
// Q1 (NPN) implements the open-collector pull-down expected by a PC-style
// 4-wire fan PWM input. It inverts the ESP GPIO signal: transistor OFF = fan
// PWM line released HIGH, so the safest electrical state is fan 100%.
//
// Fan TACH is expected to be a standard open-collector/open-drain output.
// In the reference wiring, GPIO4 reads that signal through a 2.2k series
// resistor, with an external 10k
// pull-up to ESP 3.3V. Measure the actual fan-side TACH voltage before
// connecting it. If the fan actively drives a higher voltage, use the optional
// Q2 NPN level-shifter documented in docs/WIRING.md.

static const uint8_t PWM_PIN = 5;   // GPIO5, usually D1
static const uint8_t TACH_PIN = 4;  // GPIO4, usually D2

static const uint32_t SERIAL_BAUD = 115200;
static const uint32_t PWM_FREQ_HZ = 25000;
static const uint16_t PWM_RANGE = 255;

// The firmware intentionally allows the full 0..100% range. The host daemon
// chooses a conservative automatic minimum (10% by default). This makes it
// possible to measure the real minimum-running and minimum-starting duty of
// the user's actual blower later.
// Runtime-configurable safety/tach settings. Firmware defaults are safe and are
// used when the daemon is absent; daemon v0.6+ pushes config.ini values with CFG
// after every serial reconnect, so these can be tuned without reflashing.
uint32_t commandTimeoutMs = 8000;
uint8_t tachPulsesPerRev = 2;
uint32_t rpmSampleMs = 1000;

// If a non-zero target produces no TACH activity for this long, temporarily
// force 100%. This is deliberately not applied to SET 0 because zero RPM is
// expected there during calibration/manual testing.
uint32_t stallTimeoutMs = 3000;
uint32_t stallRecoveryMs = 5000;

volatile uint32_t tachPulses = 0;
volatile bool tachActivityFlag = false;

uint32_t lastRpmSampleMs = 0;
uint32_t lastCommandMs = 0;
uint32_t nonzeroTargetSinceMs = 0;
uint32_t lastTachActivityMs = 0;
uint32_t stallRecoveryUntilMs = 0;
uint32_t stallCount = 0;

uint32_t currentRpm = 0;
uint8_t requestedFanPercent = 100;
uint8_t appliedFanPercent = 100;
bool watchdogActive = true;
bool stallRecoveryActive = false;

char lineBuffer[96];
size_t lineLength = 0;

IRAM_ATTR void onTachPulse() {
  tachPulses++;
  tachActivityFlag = true;
}

void applyElectricalFanPercent(uint8_t percent) {
  if (percent > 100) percent = 100;
  appliedFanPercent = percent;

  // Fan duty is the percentage of time its PWM input is released HIGH.
  // The NPN is ON when the ESP output is HIGH, so the GPIO duty is inverted.
  const uint8_t transistorDutyPercent = 100 - percent;
  const uint16_t pwmValue =
      (uint16_t)((transistorDutyPercent * PWM_RANGE + 50) / 100);
  analogWrite(PWM_PIN, pwmValue);
}

void requestFanPercent(uint8_t percent) {
  if (percent > 100) percent = 100;
  const uint32_t now = millis();

  const uint8_t previousTarget = requestedFanPercent;
  requestedFanPercent = percent;

  // SET 0 is an explicit manual/calibration request. It also cancels a prior
  // stall-recovery interval because zero RPM is then expected.
  if (percent == 0) {
    stallRecoveryActive = false;
    applyElectricalFanPercent(0);
    return;
  }

  // Changing one non-zero target to another must not postpone stall detection.
  // Only a true 0 -> non-zero start gets a fresh startup grace period.
  if (previousTarget == 0) {
    nonzeroTargetSinceMs = now;
  }

  if (!stallRecoveryActive) {
    applyElectricalFanPercent(percent);
  }
}

void forceMaximumFan() {
  requestedFanPercent = 100;
  stallRecoveryActive = false;
  applyElectricalFanPercent(100);
  nonzeroTargetSinceMs = millis();
}

const char *stallState() {
  return stallRecoveryActive ? "RECOVERY" : "OK";
}

void printStatus(const char *prefix) {
  Serial.print(prefix);
  Serial.print(" TARGET=");
  Serial.print(requestedFanPercent);
  Serial.print(" FAN=");
  Serial.print(appliedFanPercent);
  Serial.print(" RPM=");
  Serial.print(currentRpm);
  Serial.print(" WATCHDOG=");
  Serial.print(watchdogActive ? "FAILSAFE" : "OK");
  Serial.print(" STALL=");
  Serial.print(stallState());
  Serial.print(" STALLS=");
  Serial.println(stallCount);
}

void printConfig(const char *prefix) {
  Serial.print(prefix);
  Serial.print(" WATCHDOG_MS=");
  Serial.print(commandTimeoutMs);
  Serial.print(" STALL_MS=");
  Serial.print(stallTimeoutMs);
  Serial.print(" RECOVERY_MS=");
  Serial.print(stallRecoveryMs);
  Serial.print(" RPM_MS=");
  Serial.print(rpmSampleMs);
  Serial.print(" PPR=");
  Serial.println(tachPulsesPerRev);
}

bool parseCfg(char *args) {
  char *end = nullptr;
  unsigned long values[5];

  for (uint8_t i = 0; i < 5; i++) {
    while (*args == ' ' || *args == '\t') args++;
    if (*args == '\0') return false;
    values[i] = strtoul(args, &end, 10);
    if (end == args) return false;
    args = end;
  }

  while (*args == ' ' || *args == '\t') args++;
  if (*args != '\0') return false;

  if (values[0] < 500 || values[0] > 60000) return false;
  if (values[1] < 250 || values[1] > 60000) return false;
  if (values[2] < 250 || values[2] > 60000) return false;
  if (values[3] < 100 || values[3] > 5000) return false;
  if (values[4] < 1 || values[4] > 16) return false;

  commandTimeoutMs = (uint32_t)values[0];
  stallTimeoutMs = (uint32_t)values[1];
  stallRecoveryMs = (uint32_t)values[2];
  rpmSampleMs = (uint32_t)values[3];
  tachPulsesPerRev = (uint8_t)values[4];
  return true;
}

void handleCommand(char *line) {
  while (*line == ' ' || *line == '\t') line++;

  if (strcmp(line, "HELLO") == 0) {
    Serial.println("V100FAN 3");
    return;
  }

  if (strcmp(line, "STATUS") == 0) {
    printStatus("STATUS");
    return;
  }

  if (strcmp(line, "CONFIG") == 0) {
    printConfig("CONFIG");
    return;
  }

  if (strncmp(line, "CFG ", 4) == 0) {
    if (!parseCfg(line + 4)) {
      Serial.println("ERR CFG expects WATCHDOG_MS STALL_MS RECOVERY_MS RPM_MS PPR");
      return;
    }
    printConfig("OK CFG");
    return;
  }

  if (strcmp(line, "MAX") == 0) {
    forceMaximumFan();
    lastCommandMs = millis();
    watchdogActive = false;
    printStatus("OK");
    return;
  }

  if (strncmp(line, "SET ", 4) == 0) {
    char *end = nullptr;
    long value = strtol(line + 4, &end, 10);
    while (end && (*end == ' ' || *end == '\t')) end++;

    if (!end || *end != '\0' || value < 0 || value > 100) {
      Serial.println("ERR SET expects 0..100");
      return;
    }

    const bool rearmingFromWatchdog = watchdogActive;
    watchdogActive = false;
    requestFanPercent((uint8_t)value);
    lastCommandMs = millis();
    if (rearmingFromWatchdog && value > 0) nonzeroTargetSinceMs = millis();
    printStatus("OK");
    return;
  }

  Serial.println("ERR unknown command");
}

void updateRpm() {
  const uint32_t now = millis();

  if (tachActivityFlag) {
    noInterrupts();
    tachActivityFlag = false;
    interrupts();
    lastTachActivityMs = now;
  }

  const uint32_t elapsed = now - lastRpmSampleMs;
  if (elapsed < rpmSampleMs) return;

  noInterrupts();
  const uint32_t pulses = tachPulses;
  tachPulses = 0;
  interrupts();

  currentRpm = elapsed > 0
                   ? (uint32_t)((pulses * 60000ULL) /
                                (elapsed * tachPulsesPerRev))
                   : 0;
  lastRpmSampleMs = now;
}

void updateStallGuard() {
  const uint32_t now = millis();

  if (watchdogActive || requestedFanPercent == 0) return;

  if (stallRecoveryActive) {
    if ((int32_t)(now - stallRecoveryUntilMs) >= 0) {
      stallRecoveryActive = false;
      nonzeroTargetSinceMs = now;
      applyElectricalFanPercent(requestedFanPercent);
      Serial.print("STALL recovery complete -> retry TARGET=");
      Serial.println(requestedFanPercent);
    }
    return;
  }

  const bool targetHadTimeToStart =
      (uint32_t)(now - nonzeroTargetSinceMs) >= stallTimeoutMs;
  const bool tachMissing =
      (uint32_t)(now - lastTachActivityMs) >= stallTimeoutMs;

  if (targetHadTimeToStart && tachMissing) {
    stallCount++;
    stallRecoveryActive = true;
    stallRecoveryUntilMs = now + stallRecoveryMs;
    applyElectricalFanPercent(100);
    Serial.print("STALL no TACH -> FAN=100 for recovery, count=");
    Serial.println(stallCount);
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    const char c = (char)Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      lineBuffer[lineLength] = '\0';
      if (lineLength > 0) handleCommand(lineBuffer);
      lineLength = 0;
      continue;
    }

    if (lineLength < sizeof(lineBuffer) - 1) {
      lineBuffer[lineLength++] = c;
    } else {
      lineLength = 0;
      Serial.println("ERR line too long");
    }
  }
}

void setup() {
  // Establish the electrical fail-safe before anything else: GPIO LOW means
  // NPN OFF, so the fan PWM line is released and a standard 4-wire fan runs
  // at full speed.
  pinMode(PWM_PIN, OUTPUT);
  digitalWrite(PWM_PIN, LOW);

  pinMode(TACH_PIN, INPUT);  // fan TACH; external 10k pull-up to ESP 3.3V
  attachInterrupt(digitalPinToInterrupt(TACH_PIN), onTachPulse, FALLING);

  analogWriteRange(PWM_RANGE);
  analogWriteFreq(PWM_FREQ_HZ);
  applyElectricalFanPercent(100);

  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);

  Serial.begin(SERIAL_BAUD);
  Serial.setDebugOutput(false);

  const uint32_t now = millis();
  lastRpmSampleMs = now;
  lastCommandMs = now;
  nonzeroTargetSinceMs = now;
  lastTachActivityMs = now;
  watchdogActive = true;

  delay(20);
  Serial.println("V100FAN READY 3");
}

void loop() {
  readSerial();
  updateRpm();

  if (!watchdogActive &&
      (uint32_t)(millis() - lastCommandMs) > commandTimeoutMs) {
    forceMaximumFan();
    watchdogActive = true;
    Serial.println("FAILSAFE serial timeout -> FAN=100");
  }

  updateStallGuard();
  yield();
}
