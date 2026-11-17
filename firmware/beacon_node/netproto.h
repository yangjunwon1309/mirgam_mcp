#pragma once

#include <Arduino.h>

struct BeaconCommand {
  uint32_t id = 0;
  String type;
  String fs;
  int q = 12;
  int warm = 500;
  int fast = -1;
};

struct BeaconResponse {
  bool complete = false;
  uint32_t nextSeconds = 300;
  int holdSeconds = 0;
  String token;
  BeaconCommand commands[4];
  size_t commandCount = 0;
};

String beaconNodeId();
BeaconResponse parseBeaconResponse(const String &body, uint32_t fallbackNext);
