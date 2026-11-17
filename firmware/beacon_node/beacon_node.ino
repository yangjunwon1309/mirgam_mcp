#ifndef __has_include
#error "Compiler must support __has_include"
#endif
#if !__has_include("secrets.h")
#error "Create secrets.h with WIFI_SSID and WIFI_PASS"
#endif
#include "secrets.h"
#include "config.h"
#include "camera_cap.h"
#include "netproto.h"
#include "power.h"
#include "rtc_bm8563.h"
#include "sensors.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_heap_caps.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <math.h>

static constexpr uint32_t NORMAL_AWAKE_CAP_MS = 25000;
static constexpr uint32_t SESSION_AWAKE_CAP_MS = 180000;
static constexpr uint32_t DEFAULT_NEXT_S = 300;
static constexpr uint32_t MAX_RESPONSE_BYTES = 2048;
static constexpr uint32_t MAX_COMMANDS = 4;

static Preferences prefs;
static esp_timer_handle_t awakeTimer = nullptr;
static volatile bool awakeCapHit = false;
static bool rtcAvailable = false;
static bool cameraI2cAvailable = true;
static bool hibernateRequested = false;
static String nodeId;
static String authToken;
static uint32_t seqNumber = 0;
static uint32_t nextSaved = DEFAULT_NEXT_S;
static uint32_t wifiMs = 0;
static uint32_t checkinMs = 0;
static uint32_t batteryMv = 0;
static uint32_t tBoot = 0;
static int fastUsed = 0;
static int failCount = 0;
static String previousResult = "ok";
static uint32_t previousAwakeMs = 0;
static bool rtcTimerWake = false;
#if USB_DIAGNOSTIC_MODE
static uint32_t diagnosticStartedAt = 0;
static String diagnosticInput;
#endif
// Temporary test override: retry Wi-Fi failures after ~5 s instead of the
// production exponential backoff. Remove/revert after network validation.
static constexpr uint32_t TEST_WIFI_RETRY_SECONDS = 5;

static void awakeTimerCallback(void *) { awakeCapHit = true; }

static void startAwakeTimer(uint32_t capMs) {
  if (!awakeTimer) {
    esp_timer_create_args_t args = {};
    args.callback = awakeTimerCallback;
    args.name = "awake_cap";
    esp_timer_create(&args, &awakeTimer);
  }
  if (awakeTimer) {
    esp_timer_stop(awakeTimer);
    esp_timer_start_once(awakeTimer, (uint64_t)capMs * 1000ULL);
  }
}

static void stopAwakeTimer() {
  if (awakeTimer) esp_timer_stop(awakeTimer);
}

static void applyCycleNvs(const String &result, uint32_t awakeMs, bool success) {
  ++seqNumber;
  if (success) failCount = 0;
  else if (failCount < 255) ++failCount;
  previousResult = result;
  previousAwakeMs = awakeMs;
  prefs.putUInt("seq", seqNumber);
  prefs.putUInt("prev_ms", previousAwakeMs);
  prefs.putString("prev_res", previousResult);
  prefs.putUInt("fail", (uint32_t)failCount);
  prefs.putUInt("next", nextSaved);
}

static void powerOff(uint32_t nextSeconds, const String &result, bool success,
                     bool allowShortTestRetry = false) {
  stopAwakeTimer();
  const uint32_t minNext = allowShortTestRetry ? TEST_WIFI_RETRY_SECONDS : 30;
  if (nextSeconds < minNext) nextSeconds = minNext;
  if (nextSeconds > 15300) nextSeconds = 15300;
  nextSaved = nextSeconds;
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  applyCycleNvs(result, millis() - tBoot, success);

  bool timerSet = false;
  if (rtcAvailable) {
    timerSet = hibernateRequested ? RtcBm8563::disableTimer() : RtcBm8563::configureTimer(nextSeconds);
  }
  if (!timerSet && !hibernateRequested) {
    previousResult = "rtc_fail";
    prefs.putString("prev_res", previousResult);
  }
  Serial.printf("POWER_OFF next_s=%lu result=%s success=%d rtc_timer=%d awake_ms=%lu\n",
                (unsigned long)nextSeconds, previousResult.c_str(), success ? 1 : 0,
                timerSet ? 1 : 0, (unsigned long)(millis() - tBoot));
  Serial.flush();
  digitalWrite(33, LOW);
  delay(1000);
  beaconFallbackSleep(nextSeconds, hibernateRequested);
}

static void enforceAwakeCap() {
  if (awakeCapHit) powerOff(nextSaved, "awake_cap", false);
}

static uint32_t readBatteryMv() {
  uint64_t total = 0;
  for (int i = 0; i < 8; ++i) {
    total += analogReadMilliVolts(38);
    delay(3);
  }
  return (uint32_t)lround((double)total / 8.0 * VBAT_SCALE);
}

static bool connectWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(false);
#if USE_STATIC_IP
  IPAddress ip, gateway, mask, dns;
  ip.fromString(STATIC_IP_ADDR);
  gateway.fromString(STATIC_GW_ADDR);
  mask.fromString(STATIC_MASK_ADDR);
  dns.fromString(STATIC_DNS_ADDR);
  WiFi.config(ip, gateway, mask, dns);
#endif
  const uint32_t start = millis();
  fastUsed = 0;
  bool started = false;
  uint8_t storedBssid[6] = {};
  int channel = (int)prefs.getUInt("ch", 0);
  size_t bssidLen = prefs.getBytesLength("bssid");
  if (prefs.getBool("fast", true) && channel > 0 && bssidLen == sizeof(storedBssid)) {
    prefs.getBytes("bssid", storedBssid, sizeof(storedBssid));
    WiFi.begin(WIFI_SSID, WIFI_PASS, channel, storedBssid, true);
    started = true;
    fastUsed = 1;
    while (WiFi.status() != WL_CONNECTED && millis() - start < 5000) {
      enforceAwakeCap();
      delay(50);
    }
  }
  if (!started || WiFi.status() != WL_CONNECTED) {
    fastUsed = 0;
    WiFi.disconnect(false);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    const uint32_t fallbackStart = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - fallbackStart < 10000) {
      enforceAwakeCap();
      delay(50);
    }
  }
  wifiMs = millis() - start;
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("WIFI failed status=%d wifi_ms=%lu\n", (int)WiFi.status(),
                  (unsigned long)wifiMs);
    return false;
  }
  Serial.printf("IP=%s RSSI=%d wifi_ms=%lu fast=%d ch=%d\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI(),
                (unsigned long)wifiMs, fastUsed, WiFi.channel());
  const uint8_t *bssid = WiFi.BSSID();
  const int actualChannel = WiFi.channel();
  bool differs = actualChannel != channel || bssidLen != sizeof(storedBssid);
  if (bssid && bssidLen == sizeof(storedBssid) && memcmp(storedBssid, bssid, sizeof(storedBssid)) != 0)
    differs = true;
  if (differs && bssid) {
    prefs.putUInt("ch", (uint32_t)actualChannel);
    prefs.putBytes("bssid", bssid, 6);
  }
  return true;
}

static String baseUrl() {
  return String("http://") + SERVER_HOST + ":" + String(SERVER_PORT);
}

static void addNodeHeaders(HTTPClient &http) {
  http.addHeader("X-Node-Id", nodeId);
  if (authToken.length()) http.addHeader("X-Token", authToken);
}

static int postText(const String &path, const String &contentType, const String &body,
                    String &response, const String &extraName = "", const String &extraValue = "") {
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(3000);
  http.setTimeout(5000);
  if (!http.begin(client, baseUrl() + path)) return -1;
  addNodeHeaders(http);
  http.addHeader("Content-Type", contentType);
  if (extraName.length()) http.addHeader(extraName, extraValue);
  int code = http.POST((uint8_t *)body.c_str(), body.length());
  if (code > 0) {
    response = http.getString();
    if (response.length() > MAX_RESPONSE_BYTES) response = "";
  }
  http.end();
  return code;
}

static String makeCheckinBody() {
  const char *boot = rtcTimerWake ? "rtc" : "cold";
  if (esp_reset_reason() == ESP_RST_DEEPSLEEP) boot = "deepsleep";
  else if (esp_reset_reason() == ESP_RST_WDT || esp_reset_reason() == ESP_RST_TASK_WDT) boot = "wdt";
  char json[512];
  snprintf(json, sizeof(json),
      "{\"v\":1,\"fw\":\"beacon-0.1.0\",\"boot\":\"%s\",\"seq\":%lu,"
      "\"vbat_mv\":%lu,\"rssi\":%d,\"ch\":%d,"
      "\"t\":{\"wifi_ms\":%lu,\"fast\":%d,\"checkin_http_ms\":%lu,"
      "\"prev_awake_ms\":%lu,\"prev_result\":\"%s\"}}",
      boot, (unsigned long)seqNumber, (unsigned long)batteryMv, WiFi.RSSI(), WiFi.channel(),
      (unsigned long)wifiMs, fastUsed, (unsigned long)checkinMs,
      (unsigned long)previousAwakeMs, previousResult.c_str());
  return String(json);
}

static bool checkin(BeaconResponse &parsed, int &httpCode) {
  checkinMs = 0;
  String body = makeCheckinBody();
  const uint32_t started = millis();
  String response;
  httpCode = postText("/api/v1/checkin", "application/json", body, response);
  checkinMs = millis() - started;
  if (httpCode == 401) {
    prefs.remove("tok");
    authToken = "";
    return false;
  }
  if (httpCode != 200 || response.length() > MAX_RESPONSE_BYTES) return false;
  parsed = parseBeaconResponse(response, nextSaved);
  if (!parsed.complete) return false;
  nextSaved = parsed.nextSeconds;
  if (parsed.token.length() == 32) {
    authToken = parsed.token;
    prefs.putString("tok", authToken);
  }
  if (nextSaved != prefs.getUInt("next", DEFAULT_NEXT_S)) prefs.putUInt("next", nextSaved);
  return true;
}

static bool uploadTextResult(uint32_t commandId, const String &body) {
  String response;
  String path = "/api/v1/result?cmd=" + String(commandId);
  for (int attempt = 0; attempt < 2; ++attempt) {
    int code = postText(path, "application/json", body, response);
    if (code == 200) return true;
  }
  return false;
}

static bool uploadImageResult(uint32_t commandId, BeaconImage &image, const String &fs, int quality) {
  if (!image.data || !image.length) return false;
  const String path = baseUrl() + "/api/v1/result?cmd=" + String(commandId);
  for (int attempt = 0; attempt < 2; ++attempt) {
    WiFiClient client;
    HTTPClient http;
    http.setConnectTimeout(3000);
    http.setTimeout(5000);
    if (!http.begin(client, path)) continue;
    addNodeHeaders(http);
    http.addHeader("Content-Type", "image/jpeg");
    http.addHeader("X-Warm-Ms", String(image.warmMs));
    http.addHeader("X-Init-Ms", String(image.initMs));
    http.addHeader("X-Fs", fs);
    http.addHeader("X-Q", String(quality));
    const uint32_t started = millis();
    int code = http.POST(image.data, image.length);
    uint32_t uploadMs = millis() - started;
    Serial.printf("UPLOAD ms=%lu bytes=%u code=%d\n", (unsigned long)uploadMs,
                  (unsigned)image.length, code);
    http.end();
    if (code == 200) return true;
  }
  return false;
}

static bool validFrameSize(const String &fs) {
  return fs == "QVGA" || fs == "VGA" || fs == "SVGA" || fs == "XGA" ||
         fs == "HD" || fs == "SXGA" || fs == "UXGA";
}

static bool executeCommand(const BeaconCommand &cmd) {
  enforceAwakeCap();
  if (cmd.type == "sensor") {
    String result = readBeaconSensorsJson();
    return uploadTextResult(cmd.id, result);
  }
  if (cmd.type == "config") {
    if (cmd.fast == 0 || cmd.fast == 1) prefs.putBool("fast", cmd.fast == 1);
    return uploadTextResult(cmd.id, "{\"ok\":1}");
  }
  if (cmd.type == "hibernate") {
    hibernateRequested = true;
    return uploadTextResult(cmd.id, "{\"ok\":1}");
  }
  if (cmd.type != "image") return uploadTextResult(cmd.id, "{\"ok\":0,\"err\":\"unknown_command\"}");
  String fs = validFrameSize(cmd.fs) ? cmd.fs : "VGA";
  int quality = constrain(cmd.q, 4, 40);
  uint32_t warm = (uint32_t)constrain(cmd.warm, 0, 3000);
  BeaconImage image;
  if (!cameraI2cAvailable) image.error = "rtc_i2c_release_failed";
  else image = captureBeaconImage(fs, quality, warm);
  if (image.error.length()) {
    String error = image.error;
    error.replace("\"", "'");
    bool uploaded = uploadTextResult(cmd.id, "{\"ok\":0,\"err\":\"" + error + "\"}");
    return uploaded;
  }
  bool uploaded = uploadImageResult(cmd.id, image, fs, quality);
  freeBeaconImage(image);
  return uploaded;
}

static void executeCommands(BeaconResponse &response) {
  for (size_t i = 0; i < response.commandCount && i < MAX_COMMANDS; ++i) {
    enforceAwakeCap();
    if (!executeCommand(response.commands[i])) Serial.printf("RESULT cmd=%lu failed\n", (unsigned long)response.commands[i].id);
  }
}

static bool pollSession(int holdSeconds) {
  if (holdSeconds <= 0) return true;
  uint32_t sessionStart = millis();
  startAwakeTimer(SESSION_AWAKE_CAP_MS);
  int remaining = min(holdSeconds, 180);
  while (remaining > 0 && (uint32_t)(millis() - sessionStart) < SESSION_AWAKE_CAP_MS) {
    enforceAwakeCap();
    int waitSeconds = min(20, remaining);
    WiFiClient client;
    HTTPClient http;
    http.setConnectTimeout(3000);
    http.setTimeout((waitSeconds + 5) * 1000);
    String url = baseUrl() + "/api/v1/poll?wait=" + String(waitSeconds);
    if (!http.begin(client, url)) return false;
    addNodeHeaders(http);
    uint32_t started = millis();
    int code = http.GET();
    String response = code > 0 ? http.getString() : String();
    http.end();
    if (code != 200 || response.length() > MAX_RESPONSE_BYTES) return false;
    BeaconResponse parsed = parseBeaconResponse(response, nextSaved);
    if (!parsed.complete) return false;
    remaining = parsed.holdSeconds;
    if (parsed.token.length() == 32) {
      authToken = parsed.token;
      prefs.putString("tok", authToken);
    }
    executeCommands(parsed);
    if (millis() - started > (uint32_t)(waitSeconds + 7) * 1000U) return false;
  }
  return true;
}

#if USB_DIAGNOSTIC_MODE
static void diagnosticSleep(const char *reason) {
  Serial.printf("USB_DIAG sleeping reason=%s; press RESET to restart\n", reason);
  WiFi.disconnect(false);
  WiFi.mode(WIFI_OFF);
  RtcBm8563::end();
  Serial.flush();
  digitalWrite(33, LOW);
  delay(1000);
  esp_deep_sleep_start();
}

static void diagnosticPrintStatus() {
  uint64_t rawTotal = 0;
  uint64_t adcMvTotal = 0;
  for (int i = 0; i < 8; ++i) {
    rawTotal += (uint32_t)analogRead(38);
    adcMvTotal += (uint32_t)analogReadMilliVolts(38);
    delay(3);
  }
  const uint32_t rawAvg = (uint32_t)(rawTotal / 8);
  const uint32_t adcMvAvg = (uint32_t)(adcMvTotal / 8);
  const uint32_t scaledVbatMv = (uint32_t)lround((double)adcMvAvg * VBAT_SCALE);

  Serial.printf("DIAG_STATUS fw=beacon-0.1.0 node=%s uptime_ms=%lu reset_reason=%d\n",
                nodeId.c_str(), (unsigned long)millis(), (int)esp_reset_reason());
  Serial.printf("DIAG_NVS seq=%lu next_s=%lu fail=%d fast=%d token_present=%d prev_ms=%lu prev_result=%s\n",
                (unsigned long)seqNumber, (unsigned long)nextSaved, failCount,
                prefs.getBool("fast", true) ? 1 : 0, authToken.length() ? 1 : 0,
                (unsigned long)previousAwakeMs, previousResult.c_str());
  Serial.printf("DIAG_BATTERY gpio=38 samples=8 raw_adc_avg=%lu adc_mv_avg=%lu scale=%.2f scaled_vbat_mv=%lu calibrated=0\n",
                (unsigned long)rawAvg, (unsigned long)adcMvAvg, (double)VBAT_SCALE,
                (unsigned long)scaledVbatMv);
  Serial.printf("DIAG_MEMORY heap_free=%u psram_free=%u\n",
                (unsigned)ESP.getFreeHeap(), (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  Serial.printf("DIAG_WIFI status=%d connected=%d ip=%s rssi=%d channel=%d\n",
                (int)WiFi.status(), WiFi.status() == WL_CONNECTED ? 1 : 0,
                WiFi.localIP().toString().c_str(),
                WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0,
                WiFi.status() == WL_CONNECTED ? WiFi.channel() : 0);
  Serial.printf("DIAG_RTC available_at_boot=%d timer_wake=%d bus_released=%d\n",
                rtcAvailable ? 1 : 0, rtcTimerWake ? 1 : 0, cameraI2cAvailable ? 1 : 0);
  if (!RtcBm8563::begin()) {
    Serial.println("DIAG_RTC bus_open=failed");
    return;
  }
  Serial.print("DIAG_RTC_REGS");
  for (uint8_t reg = 0; reg <= 0x0F; ++reg) {
    uint8_t value = 0;
    if (RtcBm8563::readRegister(reg, value)) Serial.printf(" %02X:%02X", reg, value);
    else Serial.printf(" %02X:ERR", reg);
  }
  Serial.println();
  Serial.printf("DIAG_RTC bus_release=%d\n", RtcBm8563::end() ? 1 : 0);
}

static void diagnosticWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(false);
  const uint32_t started = millis();
  Serial.println("WIFI_DIAG start (SSID/password hidden; no Beacon server request)");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) delay(100);
  const bool connected = WiFi.status() == WL_CONNECTED;
  Serial.printf("WIFI_DIAG connected=%d status=%d elapsed_ms=%lu\n",
                connected ? 1 : 0, (int)WiFi.status(), (unsigned long)(millis() - started));
  if (connected) {
    Serial.printf("WIFI_DIAG ip=%s rssi=%d channel=%d\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(), WiFi.channel());
  }
  WiFi.disconnect(false);
  WiFi.mode(WIFI_OFF);
}

static void diagnosticCamera() {
  if (!cameraI2cAvailable) {
    Serial.println("CAMERA_DIAG skipped reason=rtc_i2c_release_failed");
    return;
  }
  Serial.println("CAMERA_DIAG start fs=VGA q=12 warm_ms=500");
  BeaconImage image = captureBeaconImage("VGA", 12, 500);
  if (image.error.length()) {
    Serial.printf("CAMERA_DIAG result=failed error=%s init_ms=%lu\n",
                  image.error.c_str(), (unsigned long)image.initMs);
  } else {
    bool jpegStart = image.length >= 2 && image.data[0] == 0xFF && image.data[1] == 0xD8;
    bool jpegEnd = image.length >= 2 && image.data[image.length - 2] == 0xFF && image.data[image.length - 1] == 0xD9;
    Serial.printf("CAMERA_DIAG result=ok fs=VGA width=640 height=480 bytes=%u init_ms=%lu warm_ms=%lu jpeg_soi=%d jpeg_eoi=%d\n",
                  (unsigned)image.length, (unsigned long)image.initMs,
                  (unsigned long)image.warmMs, jpegStart ? 1 : 0, jpegEnd ? 1 : 0);
  }
  freeBeaconImage(image);
}

static void diagnosticHelp() {
  Serial.println("USB_DIAG commands:");
  Serial.println("  help     show commands");
  Serial.println("  status   chip, reset, NVS, battery ADC, Wi-Fi state, heap/PSRAM, RTC registers");
  Serial.println("  i2c      scan Grove G4/G13 in both SDA/SCL orders, RTC and camera SCCB buses");
  Serial.println("  sensor   test both Grove wire orders; print line levels, raw bytes, CRC and values");
  Serial.println("  wifi     join configured Wi-Fi and print IP/RSSI/channel; does not contact Beacon server");
  Serial.println("  camera   init OV3660 and capture one VGA JPEG; print init/capture diagnostics");
  Serial.println("  all      run status, I2C scan, sensor read, camera test and Wi-Fi check");
  Serial.println("  sleep    stop diagnostics and enter deep sleep; press RESET to restart");
  Serial.println("No SSID, password or token value is printed. Diagnostic mode requires USB power.");
}

static void runDiagnosticCommand(String command) {
  command.trim();
  command.toLowerCase();
  if (!command.length()) return;
  Serial.printf("USB_DIAG command=%s\n", command.c_str());
  if (command == "help") diagnosticHelp();
  else if (command == "status") diagnosticPrintStatus();
  else if (command == "i2c") printBeaconI2cScans();
  else if (command == "sensor") diagnoseBeaconSensorWiring();
  else if (command == "wifi") diagnosticWifi();
  else if (command == "camera") diagnosticCamera();
  else if (command == "all") {
    diagnosticPrintStatus();
    printBeaconI2cScans();
    diagnoseBeaconSensorWiring();
    diagnosticCamera();
    diagnosticWifi();
  }
  else if (command == "sleep" || command == "exit") diagnosticSleep("user_request");
  else Serial.println("USB_DIAG unknown_command; type help");
}

static void pollDiagnosticConsole() {
  if (millis() - diagnosticStartedAt >= USB_DIAGNOSTIC_MAX_RUNTIME_MS)
    diagnosticSleep("runtime_limit");
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      runDiagnosticCommand(diagnosticInput);
      diagnosticInput = "";
      Serial.print("usb-diag> ");
    } else if (diagnosticInput.length() < 80) {
      diagnosticInput += c;
    } else {
      diagnosticInput = "";
      Serial.println("USB_DIAG input_too_long");
    }
  }
}
#endif

void setup() {
  pinMode(33, OUTPUT);
  digitalWrite(33, HIGH);
  tBoot = millis();
#if !USB_DIAGNOSTIC_MODE
  startAwakeTimer(NORMAL_AWAKE_CAP_MS);
#endif
  Serial.begin(115200);
  Serial.println("BOOT fw=beacon-0.1.0");

  rtcAvailable = RtcBm8563::begin();
  if (rtcAvailable) rtcAvailable = RtcBm8563::detectTimerWakeAndClear(rtcTimerWake);
  // esp_camera's SCCB driver claims I2C controller 1 on this core. Release
  // Wire1 after the boot-time RTC read, then reopen it in powerOff() after
  // camera deinit so the two drivers never own the same controller together.
  cameraI2cAvailable = RtcBm8563::end();
  Serial.printf("RTC I2C released_for_camera=%d\n", cameraI2cAvailable ? 1 : 0);
  nodeId = beaconNodeId();
  prefs.begin("beacon", false);
  seqNumber = prefs.getUInt("seq", 0);
  nextSaved = prefs.getUInt("next", DEFAULT_NEXT_S);
  if (nextSaved < 30 || nextSaved > 15300) nextSaved = DEFAULT_NEXT_S;
  authToken = prefs.getString("tok", "");
  failCount = (int)prefs.getUInt("fail", 0);
  previousAwakeMs = prefs.getUInt("prev_ms", 0);
  previousResult = prefs.getString("prev_res", "ok");
  batteryMv = readBatteryMv();
  Serial.printf("RTC available=%d timer_wake=%d seq=%lu vbat_mv=%lu\n",
                rtcAvailable ? 1 : 0, rtcTimerWake ? 1 : 0,
                (unsigned long)seqNumber, (unsigned long)batteryMv);

#if USB_DIAGNOSTIC_MODE
  diagnosticStartedAt = millis();
  Serial.println("USB_DIAG_READY server_disabled=1 mode=serial_console");
  Serial.println("Type help and press Enter. Maximum run time is 15 minutes; use USB power.");
  Serial.print("usb-diag> ");
  return;
#endif

  if (!connectWifi()) {
    powerOff(TEST_WIFI_RETRY_SECONDS, "wifi_fail", false, true);
  }

  BeaconResponse response;
  int code = 0;
  if (!checkin(response, code)) {
    Serial.printf("CHECKIN failed http=%d elapsed_ms=%lu\n", code,
                  (unsigned long)checkinMs);
    if (code == 401) powerOff(nextSaved, "http_fail", false);
    uint32_t multiplier = 1U << min(failCount + 1, 3);
    uint32_t backoff = min((uint32_t)3600, max((uint32_t)30, nextSaved) * multiplier);
    powerOff(backoff, "http_fail", false);
  }
  Serial.printf("CHECKIN ok next_s=%lu hold_s=%d commands=%u\n",
                (unsigned long)response.nextSeconds, response.holdSeconds,
                (unsigned)response.commandCount);
  failCount = 0;
  executeCommands(response);
  if (response.holdSeconds > 0) pollSession(response.holdSeconds);
  powerOff(nextSaved, "ok", true);
}

void loop() {
#if USB_DIAGNOSTIC_MODE
  pollDiagnosticConsole();
  delay(10);
#else
  enforceAwakeCap();
  delay(20);
#endif
}
