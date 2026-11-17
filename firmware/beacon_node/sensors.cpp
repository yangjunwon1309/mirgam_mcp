#include "sensors.h"
#include <Wire.h>
#include <string.h>

static uint8_t crc8(const uint8_t *data, size_t len) {
  uint8_t crc = 0xFF;
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
  }
  return crc;
}

static size_t readBytes(uint8_t address, uint8_t *data, size_t count) {
  const size_t received = Wire.requestFrom((int)address, (int)count);
  if (received != count) {
    while (Wire.available()) Wire.read();
    return received;
  }
  for (size_t i = 0; i < count; ++i) data[i] = (uint8_t)Wire.read();
  return received;
}

static const char *deviceHint(uint8_t address, const char *busName) {
  if (strcmp(busName, "grove") == 0 && (address == 0x44 || address == 0x45)) return "SHT30_candidate";
  if (strcmp(busName, "grove") == 0 && address == 0x38) return "DHT20_candidate";
  if (strcmp(busName, "rtc") == 0 && address == 0x51) return "BM8563";
  if (strcmp(busName, "camera_sccb") == 0 && address == 0x3C) return "OV3660_candidate";
  return "unknown";
}

static void scanBus(TwoWire &bus, const char *name, int sda, int scl) {
  Serial.printf("I2C_SCAN bus=%s sda=%d scl=%d hz=100000\n", name, sda, scl);
  if (!bus.begin(sda, scl, 100000)) {
    Serial.printf("I2C_SCAN bus=%s init=failed\n", name);
    return;
  }
  unsigned found = 0;
  for (uint8_t address = 0x08; address <= 0x77; ++address) {
    bus.beginTransmission(address);
    const uint8_t result = bus.endTransmission();
    if (result == 0) {
      ++found;
      Serial.printf("I2C_DEVICE bus=%s addr=0x%02X decimal=%u hint=%s\n",
                    name, address, address, deviceHint(address, name));
    }
  }
  Serial.printf("I2C_SCAN_DONE bus=%s devices=%u\n", name, found);
  bus.end();
}

void printBeaconI2cScans() {
  scanBus(Wire, "grove", 4, 13);
  scanBus(Wire, "grove_swapped", 13, 4);
  // The RTC and the camera SCCB share ESP32 controller 1. Scan them
  // sequentially on their respective pins; never keep both bus owners active.
  scanBus(Wire1, "rtc", 12, 14);
  scanBus(Wire1, "camera_sccb", 25, 23);
}

static void printI2cIdleLevels(int sda, int scl, const char *orientation) {
  pinMode(sda, INPUT_PULLUP);
  pinMode(scl, INPUT_PULLUP);
  delay(2);
  const int sdaLevel = digitalRead(sda);
  const int sclLevel = digitalRead(scl);
  Serial.printf("I2C_LINES orientation=%s sda_gpio=%d level=%d scl_gpio=%d level=%d\n",
                orientation, sda, sdaLevel, scl, sclLevel);
  pinMode(sda, INPUT);
  pinMode(scl, INPUT);
}

void diagnoseBeaconSensorWiring() {
  printI2cIdleLevels(4, 13, "G4_SDA_G13_SCL");
  Serial.println("SENSOR_WIRING_TEST orientation=G4_SDA_G13_SCL");
  readBeaconSensorsJson(true, 4, 13);
  printI2cIdleLevels(13, 4, "G13_SDA_G4_SCL");
  Serial.println("SENSOR_WIRING_TEST orientation=G13_SDA_G4_SCL");
  readBeaconSensorsJson(true, 13, 4);
}

String readBeaconSensorsJson(bool verbose, int sda, int scl) {
  if (!Wire.begin(sda, scl, 100000)) {
    if (verbose) Serial.printf("SENSOR bus_init=failed sda=%d scl=%d\n", sda, scl);
    return "{\"ok\":0,\"err\":\"i2c_bus_init_failed\"}";
  }
  if (verbose) Serial.printf("SENSOR bus=grove sda=%d scl=%d hz=100000\n", sda, scl);

  String entries;
  bool first = true;
  for (uint8_t address : {(uint8_t)0x44, (uint8_t)0x45}) {
    Wire.beginTransmission(address);
    Wire.write(0x24);
    Wire.write(0x00);
    const uint8_t txResult = Wire.endTransmission();
    if (verbose) Serial.printf("SHT30 addr=0x%02X command=24,00 tx_result=%u\n", address, txResult);
    if (txResult != 0) continue;

    delay(20);
    uint8_t data[6] = {};
    const size_t received = readBytes(address, data, sizeof(data));
    if (received != sizeof(data)) {
      if (verbose) Serial.printf("SHT30 addr=0x%02X received=%u expected=6\n", address, (unsigned)received);
      continue;
    }
    const bool tempCrcOk = crc8(data, 2) == data[2];
    const bool humidityCrcOk = crc8(data + 3, 2) == data[5];
    if (verbose) {
      Serial.printf("SHT30 addr=0x%02X raw=%02X,%02X,%02X,%02X,%02X,%02X crc_t=%s crc_rh=%s\n",
                    address, data[0], data[1], data[2], data[3], data[4], data[5],
                    tempCrcOk ? "ok" : "bad", humidityCrcOk ? "ok" : "bad");
    }
    if (!tempCrcOk || !humidityCrcOk) continue;

    const uint16_t rawT = ((uint16_t)data[0] << 8) | data[1];
    const uint16_t rawH = ((uint16_t)data[3] << 8) | data[4];
    const float temperature = -45.0f + 175.0f * (float)rawT / 65535.0f;
    const float humidity = 100.0f * (float)rawH / 65535.0f;
    if (!first) entries += ',';
    entries += "{\"type\":\"sht30\",\"addr\":" + String(address) +
               ",\"t_c\":" + String(temperature, 2) + ",\"rh\":" + String(humidity, 2) + "}";
    first = false;
    if (verbose) Serial.printf("SHT30 addr=0x%02X temperature_c=%.2f humidity_pct=%.2f\n",
                              address, temperature, humidity);
  }

  const uint8_t dhtAddress = 0x38;
  Wire.beginTransmission(dhtAddress);
  const uint8_t probeResult = Wire.endTransmission();
  if (verbose) Serial.printf("DHT20 addr=0x38 probe_result=%u\n", probeResult);
  if (probeResult == 0) {
    delay(100);
    Wire.beginTransmission(dhtAddress);
    Wire.write(0x71);
    const uint8_t statusTx = Wire.endTransmission(false);
    uint8_t status = 0;
    const size_t statusBytes = statusTx == 0 ? readBytes(dhtAddress, &status, 1) : 0;
    const bool calibrated = statusTx == 0 && statusBytes == 1 && (status & 0x08);
    if (verbose) Serial.printf("DHT20 status_tx=%u bytes=%u status=0x%02X calibrated=%d\n",
                               statusTx, (unsigned)statusBytes, status, calibrated ? 1 : 0);
    if (calibrated) {
      Wire.beginTransmission(dhtAddress);
      Wire.write(0xAC);
      Wire.write(0x33);
      Wire.write(0x00);
      const uint8_t measureTx = Wire.endTransmission();
      if (verbose) Serial.printf("DHT20 measure_command=AC,33,00 tx_result=%u\n", measureTx);
      if (measureTx == 0) {
        delay(80);
        uint8_t data[7] = {};
        const size_t received = readBytes(dhtAddress, data, sizeof(data));
        const bool crcOk = received == sizeof(data) && crc8(data, 6) == data[6];
        if (verbose) {
          Serial.printf("DHT20 received=%u raw=%02X,%02X,%02X,%02X,%02X,%02X,%02X crc=%s\n",
                        (unsigned)received, data[0], data[1], data[2], data[3],
                        data[4], data[5], data[6], crcOk ? "ok" : "bad");
        }
        if (crcOk) {
          const uint32_t rawH = ((uint32_t)data[1] << 12) | ((uint32_t)data[2] << 4) | (data[3] >> 4);
          const uint32_t rawT = (((uint32_t)data[3] & 0x0F) << 16) | ((uint32_t)data[4] << 8) | data[5];
          const float humidity = 100.0f * (float)rawH / 1048576.0f;
          const float temperature = 200.0f * (float)rawT / 1048576.0f - 50.0f;
          if (!first) entries += ',';
          entries += "{\"type\":\"dht20\",\"addr\":56,\"t_c\":" + String(temperature, 2) +
                     ",\"rh\":" + String(humidity, 2) + "}";
          first = false;
          if (verbose) Serial.printf("DHT20 temperature_c=%.2f humidity_pct=%.2f\n",
                                     temperature, humidity);
        }
      }
    }
  }

  Wire.end();
  if (first) {
    if (verbose) Serial.println("SENSOR_RESULT=sensor_absent_or_invalid");
    const String result = "{\"ok\":0,\"err\":\"sensor_absent\"}";
    if (verbose) Serial.println("SENSOR_JSON=" + result);
    return result;
  }
  const String result = "{\"ok\":1,\"sensors\":[" + entries + "]}";
  if (verbose) Serial.println("SENSOR_JSON=" + result);
  return result;
}
