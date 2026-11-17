#pragma once

#include <Arduino.h>

void printBeaconI2cScans();
void diagnoseBeaconSensorWiring();
String readBeaconSensorsJson(bool verbose = false, int sda = 4, int scl = 13);
