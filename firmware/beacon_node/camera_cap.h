#pragma once

#include <Arduino.h>

struct BeaconImage {
  uint8_t *data = nullptr;
  size_t length = 0;
  uint32_t initMs = 0;
  uint32_t warmMs = 0;
  String error;
};

BeaconImage captureBeaconImage(const String &frameSize, int quality, uint32_t warmMs);
void freeBeaconImage(BeaconImage &image);
