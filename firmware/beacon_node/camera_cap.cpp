#include "camera_cap.h"
#include "esp_camera.h"
#include "esp_heap_caps.h"

static framesize_t parseFrameSize(const String &name) {
  if (name == "QVGA") return FRAMESIZE_QVGA;
  if (name == "SVGA") return FRAMESIZE_SVGA;
  if (name == "XGA") return FRAMESIZE_XGA;
  if (name == "HD") return FRAMESIZE_HD;
  if (name == "SXGA") return FRAMESIZE_SXGA;
  if (name == "UXGA") return FRAMESIZE_UXGA;
  return FRAMESIZE_VGA;
}

BeaconImage captureBeaconImage(const String &frameSize, int quality, uint32_t warmMs) {
  BeaconImage result;
  const framesize_t fs = parseFrameSize(frameSize);
  camera_config_t config = {};
  config.pin_pwdn = -1;
  config.pin_reset = 15;
  config.pin_xclk = 27;
  config.pin_sccb_sda = 25;
  config.pin_sccb_scl = 23;
  config.pin_d7 = 19;
  config.pin_d6 = 36;
  config.pin_d5 = 18;
  config.pin_d4 = 39;
  config.pin_d3 = 5;
  config.pin_d2 = 34;
  config.pin_d1 = 35;
  config.pin_d0 = 32;
  config.pin_vsync = 22;
  config.pin_href = 26;
  config.pin_pclk = 21;
  config.xclk_freq_hz = 20000000;
  config.ledc_timer = LEDC_TIMER_0;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = fs;
  config.jpeg_quality = constrain(quality, 4, 40);
  config.fb_count = 1;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  uint32_t pixels = 640U * 480U;
  switch (fs) {
    case FRAMESIZE_QVGA: pixels = 320U * 240U; break;
    case FRAMESIZE_VGA: pixels = 640U * 480U; break;
    case FRAMESIZE_SVGA: pixels = 800U * 600U; break;
    case FRAMESIZE_XGA: pixels = 1024U * 768U; break;
    case FRAMESIZE_HD: pixels = 1280U * 720U; break;
    case FRAMESIZE_SXGA: pixels = 1280U * 1024U; break;
    case FRAMESIZE_UXGA: pixels = 1600U * 1200U; break;
    default: break;
  }
  config.jpeg_buffer_size = max((size_t)(128U * 1024U), (size_t)(pixels / 3U));
  const uint32_t initStarted = millis();
  esp_err_t err = esp_camera_init(&config);
  result.initMs = millis() - initStarted;
  if (err != ESP_OK) {
    char message[40];
    snprintf(message, sizeof(message), "camera_init 0x%x", (unsigned)err);
    result.error = message;
    return result;
  }
  const uint32_t started = millis();
  camera_fb_t *fb = nullptr;
  do {
    fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
    fb = nullptr;
    if ((uint32_t)(millis() - started) >= warmMs) break;
    delay(10);
  } while (true);
  result.warmMs = millis() - started;
  fb = esp_camera_fb_get();
  if (!fb) {
    result.error = "camera_capture_failed";
    esp_camera_deinit();
    return result;
  }
  result.data = (uint8_t *)ps_malloc(fb->len);
  if (!result.data) {
    result.error = "camera_alloc_failed";
  } else {
    memcpy(result.data, fb->buf, fb->len);
    result.length = fb->len;
  }
  esp_camera_fb_return(fb);
  esp_camera_deinit();
  return result;
}

void freeBeaconImage(BeaconImage &image) {
  if (image.data) free(image.data);
  image.data = nullptr;
  image.length = 0;
}
