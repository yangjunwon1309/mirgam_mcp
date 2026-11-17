#include "power.h"
#include <esp_sleep.h>

void beaconFallbackSleep(uint32_t seconds, bool hibernate) {
  if (!hibernate) esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_deep_sleep_start();
}
