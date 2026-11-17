#include "rtc_bm8563.h"

namespace RtcBm8563 {
static bool busStarted = false;

static bool readReg(uint8_t reg, uint8_t &value) {
  Wire1.beginTransmission(ADDRESS);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom((int)ADDRESS, 1) != 1) return false;
  value = (uint8_t)Wire1.read();
  return true;
}

static bool writeReg(uint8_t reg, uint8_t value) {
  Wire1.beginTransmission(ADDRESS);
  Wire1.write(reg);
  Wire1.write(value);
  return Wire1.endTransmission() == 0;
}

bool begin() {
  if (busStarted) return true;
  busStarted = Wire1.begin(12, 14, 100000);
  return busStarted;
}
bool end() {
  if (!busStarted) return true;
  const bool ended = Wire1.end();
  if (ended) busStarted = false;
  return ended;
}
bool readRegister(uint8_t reg, uint8_t &value) { return readReg(reg, value); }
bool writeRegister(uint8_t reg, uint8_t value) { return writeReg(reg, value); }

static bool timerCountMatchesFirstPeriod(uint8_t programmed, uint8_t observed) {
  // PCF8563 starts its countdown asynchronously to I2C. The first period can
  // be one source-clock tick shorter, so the live counter may already be n-1.
  return observed == programmed || (programmed > 1 && observed == programmed - 1);
}

bool stopTimerAndClearFlags() {
  uint8_t control2 = 0;
  if (!readReg(0x01, control2)) return false;
  control2 &= 0x02; // Keep AIE only; clear TI_TP, AF, TF, TIE and reserved bits.
  if (!writeReg(0x01, control2)) return false;
  uint8_t timerControl = 0;
  if (!readReg(0x0E, timerControl)) return false;
  timerControl &= 0x03; // Keep TD, clear TE and reserved bits.
  return writeReg(0x0E, timerControl);
}

bool detectTimerWakeAndClear(bool &timerWake) {
  uint8_t control2 = 0;
  if (!readReg(0x01, control2)) return false;
  timerWake = (control2 & 0x04) != 0;
  control2 &= 0x02; // Keep AIE only; clear TI_TP, AF, TF, TIE and reserved bits.
  return writeReg(0x01, control2);
}

bool disableTimer() {
  if (!begin()) return false;
  for (int attempt = 0; attempt < 3; ++attempt) {
    if (stopTimerAndClearFlags() && writeReg(0x0F, 0)) {
      uint8_t c2 = 0, tc = 0, tv = 0;
      if (readReg(0x01, c2) && readReg(0x0E, tc) && readReg(0x0F, tv) &&
          !(c2 & 0x05) && !(tc & 0x80) && tv == 0) return true;
    }
  }
  return false;
}

bool configureTimer(uint32_t seconds) {
  if (!begin()) return false;
  if (seconds < 1) seconds = 1;
  if (seconds > 15300) seconds = 15300;
  uint8_t td;
  uint8_t ticks;
  if (seconds <= 255) {
    td = 0x02; // TD=10: 1 Hz
    ticks = (uint8_t)seconds;
  } else {
    td = 0x03; // TD=11: 1/60 Hz
    uint32_t rounded = (seconds + 30) / 60;
    if (rounded < 1) rounded = 1;
    if (rounded > 255) rounded = 255;
    ticks = (uint8_t)rounded;
  }

  const uint8_t expectedControl = (uint8_t)(0x80 | td);
  for (int attempt = 0; attempt < 3; ++attempt) {
    if (!stopTimerAndClearFlags()) {
      Serial.printf("RTC_TIMER attempt=%d stage=stop_clear_failed\n", attempt + 1);
      continue;
    }
    if (!writeReg(0x0F, ticks)) {
      Serial.printf("RTC_TIMER attempt=%d stage=counter_write_failed\n", attempt + 1);
      continue;
    }
    if (!writeReg(0x0E, expectedControl)) {
      Serial.printf("RTC_TIMER attempt=%d stage=control_write_failed\n", attempt + 1);
      continue;
    }
    uint8_t control2 = 0;
    if (!readReg(0x01, control2)) {
      Serial.printf("RTC_TIMER attempt=%d stage=status_read_failed\n", attempt + 1);
      continue;
    }
    control2 = (uint8_t)((control2 & 0x02) | 0x01); // Preserve AIE; TIE=1, TI_TP=0, AF/TF=0.
    if (!writeReg(0x01, control2)) {
      Serial.printf("RTC_TIMER attempt=%d stage=status_write_failed\n", attempt + 1);
      continue;
    }
    uint8_t verify2 = 0, verifyControl = 0, verifyValue = 0, verifyValueAgain = 0;
    bool readStatus = readReg(0x01, verify2);
    bool readControl = readReg(0x0E, verifyControl);
    bool readValue = readReg(0x0F, verifyValue);
    bool readValueAgainOk = readReg(0x0F, verifyValueAgain);
    if (readStatus && readControl && readValue && (verify2 & 0x01) &&
        !(verify2 & 0x04) && verifyControl == expectedControl &&
        readValueAgainOk && verifyValue == verifyValueAgain &&
        timerCountMatchesFirstPeriod(ticks, verifyValue)) {
      if (verifyValue != ticks) {
        Serial.printf("RTC_TIMER armed=1 requested_ticks=%u read_ticks=%u first_tick_short=1\n",
                      ticks, verifyValue);
      }
      return true;
    }
    Serial.printf("RTC_TIMER attempt=%d verify_read=%d c2=%02X tc=%02X tv=%02X tv2=%02X expected_tc=%02X tv=%02X\n",
                  attempt + 1,
                  readStatus && readControl && readValue && readValueAgainOk ? 1 : 0,
                  verify2, verifyControl, verifyValue, verifyValueAgain,
                  expectedControl, ticks);
  }
  return false;
}
}
