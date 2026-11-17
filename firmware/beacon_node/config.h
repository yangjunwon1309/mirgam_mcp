#pragma once

// Server address is intentionally defined in this file only.
#define SERVER_HOST "192.168.219.123"
#define SERVER_PORT 8080
#define USE_STATIC_IP 0

// Set to 1 only in a diagnostic build compiled with
// -DUSB_DIAGNOSTIC_MODE=1. Production builds leave serial diagnostics off.
#ifndef USB_DIAGNOSTIC_MODE
#define USB_DIAGNOSTIC_MODE 0
#endif
#define USB_DIAGNOSTIC_MAX_RUNTIME_MS 900000UL

// Calibrate against a multimeter before using battery telemetry for policy.
#define VBAT_SCALE 2.0f

