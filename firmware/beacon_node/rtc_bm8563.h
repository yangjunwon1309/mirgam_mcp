#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace RtcBm8563 {
constexpr uint8_t ADDRESS = 0x51;
bool begin();
bool end();
bool readRegister(uint8_t reg, uint8_t &value);
bool writeRegister(uint8_t reg, uint8_t value);
bool detectTimerWakeAndClear(bool &timerWake);
bool stopTimerAndClearFlags();
bool configureTimer(uint32_t seconds);
bool disableTimer();
}
