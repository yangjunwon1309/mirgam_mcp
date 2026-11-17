# 농장 비콘 다대일 통신 개발 명세서 (SPEC_NET v1)

작업자: Codex (Jetson 셸) + 사람(업로드·하드웨어 측정). 이 문서가 유일한 요구사항이다. 명세와 현실이 어긋나면 추측해서 진행하지 말고 14절대로 중단하고 보고한다.

---

## 0. 목적과 범위

여러 대의 배터리 ESP32 Timer Camera(U082) 노드(N)와 상시 전원 Jetson 서버(1) 사이의 다대일 통신을 구현한다.

- Jetson이 노드를 등록(연결)/해제할 수 있어야 한다. 지금은 CLI로 제어하고, 대시보드는 나중에 같은 관리 API 위에 만든다.
- 등록된 노드의 카메라 이미지와 센서값은 Jetson이 요청할 때만 얻는다. 노드는 요청이 없으면 측정하지 않는다.
- 최우선 목표는 노드의 평균 소비 전력 최소화다. 목표 배터리 교체 주기는 1개월 이상이다.

범위 밖: 대시보드 UI, OTA 펌웨어 업데이트, TLS, 인터넷 노출, LLM 연동, 이미지 분석.

---

## 1. 전제 (확인 상태 표시)

| 항목 | 값 | 상태 |
|---|---|---|
| 서버 | Jetson, Ubuntu 22.04 aarch64, Python 3.10, 사용자 nano, 데이터는 /mnt/nvme | 확인 |
| 네트워크 | iptime 공유기 2.4 GHz, 노드·서버는 192.168.25.0/24, 게이트웨이 192.168.25.1. Jetson의 노드 접속 주소는 wlP1p1s0=192.168.25.19. enP8p1s0=192.168.137.152는 관리 링크이며 노드 통신에 사용하지 않는다. 노드 주소 192.168.25.45가 시리얼에서 관측됨. 172.30.1.0/24는 더 이상 사용하지 않는다 | 확인 |
| 노드 | M5Stack Timer Camera U082 (ESP32, PSRAM, OV3660), FQBN esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000, 코어 3.3.12 | 확인 |
| 전원 유지 | GPIO33(BAT_HOLD) HIGH면 배터리 전원 유지, LOW면 차단(USB 전원 시에는 꺼지지 않음) | M5 문서 기준, 실측 필요 |
| 깨우기 | BM8563 RTC(I2C 0x51, SDA=G12, SCL=G14)의 인터럽트가 전원을 다시 켬 | M5 문서 기준, 실측 필요 |
| 꺼진 상태 전류 | 보드 2 µA(M5 문서) ~ 10 µA(다른 자료) + 충전 모듈·보호회로 미상 | 미측정 |
| 센서 버스 | Grove I2C SDA=G4, SCL=G13. SHT30(0x44 또는 0x45), DHT20(0x38) | 핀은 문서 기준. 센서는 아직 미연결 |
| 배터리 ADC | GPIO38. 분압비 미확인 | 보정 필요 |
| 카메라 수렴 | 부팅 1회 예비 측정에서 init 후 약 0.4 s에 평균 휘도가 정상 상태 ±5 근처 도달 | 예비값. cam_test 본 측정으로 갱신 |
| 시리얼 모니터 | arduino-cli monitor는 -c dtr=off -c rts=off가 필요하고 timeout -s INT -k 3으로 끝내야 함 | 확인 |

---

## 2. 분석 요약 (설계 근거)

### 2.1 노드는 상시 수신 대기를 할 수 없다

Jetson이 원할 때 노드에 바로 연결하려면(서버 푸시) 노드가 Wi-Fi에 계속 붙어 있어야 한다. ESP32가 Wi-Fi 연결을 유지하면 절전 모드(DTIM 기반 light sleep)에서도 평균 수 mA가 들고, 보드 레귤레이터와 카메라 대기 전류가 더해진다. 배터리 예산은 2600 mAh × 0.6(가용 비율 가정) / 30일 = 약 52 mAh/일 ≈ 평균 2.2 mA다. 상시 연결은 이 예산과 같은 크기이거나 넘을 가능성이 커서 배제한다.

따라서 노드가 깨어나서 서버에 먼저 묻는 구조(풀 방식)만 가능하다. 노드는 대부분의 시간 동안 BAT_HOLD로 전원을 완전히 끄고, BM8563 타이머로 다시 켜진다. 이 구조에서 요청-응답 지연 상한은 체크인 주기 T다. 이는 전력과 지연 사이의 근본 교환 관계이며, 아래 설계는 서버가 이를 조절한다.

### 2.2 통신 방식 비교

| 방식 | 장점 | 단점 | 판단 |
|---|---|---|---|
| HTTP/1.1 over TCP (노드=클라이언트) | 요청-응답 의미가 명확해 명령 수신/결과 업로드가 결정적이다. 이미지 바이너리 업로드가 자연스럽다. 코어 내장 HTTPClient와 Python 표준 라이브러리 서버 사용 | 체크인마다 TCP 연결을 새로 맺는다. LAN 수 ms는 Wi-Fi 접속 시간에 비해 무시 가능 | 채택 |
| MQTT (broker 경유) | pub/sub, 지속 세션 큐 | 브로커 운영 추가. 깨어난 뒤 대기 메시지가 모두 도착했는지 알기 어렵다. 이미지 이득 없음 | 보류. 대시보드 실시간 표시 때 서버 내부에서 검토 |
| CoAP/UDP | 헤더가 작음 | 이미지 블록 전송·재전송 직접 구현. 에너지 절약 효과가 작음 | 배제 |
| 직접 TCP 소켓 | 오버헤드 최소 | 프레이밍, 재시도, 디버깅 직접 구현 | 배제 |
| ESP-NOW | 접속 절차 없음 | 공유기망 사용 가능. ACK/재전송이 없고 이미지에 부적합 | 배제 |

결론: 노드는 HTTP 클라이언트, Jetson은 HTTP 서버다. 노드는 서버 포트를 열지 않는다.

### 2.3 “핸드셰이크 때 요청을 확인”하는 방식의 보강

주기 체크인 때 서버의 명령 큐를 확인하는 메일박스 방식에 다음을 더한다.

1. 서버가 체크인 응답의 next(초)로 다음 체크인 시각을 정한다. 등록/해제, 배터리, 워치 상태에 따라 조절한다.
2. 명령은 체크인 응답에 함께 실어 별도 왕복을 줄인다.
3. 결과는 같은 깨어남 안에서 업로드하며 노드는 결과를 저장하지 않는다.
4. 상호작용 때 서버가 hold를 주면 노드는 최대 hold초 동안 GET /poll 롱폴을 한다. 첫 연결까지는 최대 T, 세션 중 응답은 1초 이내 목표다.
5. 워치 중에는 기본 60 s 주기를 주고 watch_until 뒤 원래 주기로 복귀한다.
6. 노드는 깨어 있는 시간 상한을 두고, 배터리가 낮으면 서버와 노드 양쪽에서 이미지 명령을 거부하고 주기를 늘린다.

전달 보장은 최소 1회(at-least-once)+서버 측 중복 제거다. 전원 차단 시 노드 기억은 사라진다. 서버는 cmd_id로 중복 결과를 버린다. 센서 측정과 사진 촬영은 재실행 가능하다.

### 2.4 에너지 모델

하루 소모량:

```
E_day = N_c · E_c + N_img · E_img + N_s · E_s + I_off · 24 h
N_c = 86400 / T
```

가정값(실측으로 바꿀 것):

| 기호 | 의미 | 가정 | 근거 |
|---|---|---|---|
| E_c 빠른 접속 | 부팅+Wi-Fi(채널/BSSID 캐시)+HTTP | 120 mA×1.5 s=0.050 mAh | 일반 ESP32 |
| E_c 느린 접속 | 스캔+DHCP | 120 mA×3.5 s=0.117 mAh | 일반 ESP32 |
| E_img | 카메라 init/워밍업/촬영/50 KB 업로드 추가분 | 160 mA×1.2 s=0.053 mAh | 일반 ESP32 |
| E_s | 센서 1회 | 약 0.001 mAh | 무시 가정 |
| I_off | 꺼진 전체 회로 | 20 µA=0.48 mAh/일 | 보수적 가정 |

이미지 24장/일 기준:

| 체크인 주기 T | 빠른 접속 | 느린 접속 |
|---|---|---|
| 60 s | 73.8 mAh/일 → 21일 | 169.8 → 9일 |
| 120 s | 37.8 → 41일 | 85.8 → 18일 |
| 300 s (기본값) | 16.2 → 97일 | 35.4 → 44일 |
| 600 s | 9.0 → 174일 | 18.6 → 84일 |
| 900 s | 6.6 → 238일 | 13.0 → 120일 |

30일 최소 주기는 빠른 접속 약 86 s, 느린 접속 약 201 s다. 60초 세션은 약 1.8 mAh(체크인 약 37회분)다.

소비의 대부분은 체크인 횟수×접속 시간이다. 우선 최적화는 Wi-Fi 접속 시간(채널/BSSID 캐시, 고정 IP), 다음은 서버 주기 조절이다. 기본 주기는 300 s다. 이 표는 가정이며 6.9절 기록과 13절 전류 측정으로 E_c/E_img를 갱신한다.

### 2.5 지연 시간

| 상황 | 요청 후 결과까지 |
|---|---|
| 일반(T=300 s) | 최대 약 T+수 초, 평균 약 T/2 |
| 워치(T=60 s) | 최대 약 60 s+수 초 |
| 세션 중 | 센서 약 1 s, 이미지 약 1~2 s |

---

## 3. 시스템 구성

```
[노드 tc-xxxxxx] -- Wi-Fi, HTTP :8080 --> [Jetson beacon-server]
                                      <-- 127.0.0.1:8081 관리 API -- beaconctl
BM8563 타이머로 전원 ON; 작업 후 GPIO33 LOW로 전원 OFF
SQLite + 이미지 (/mnt/nvme/beacon)
```

디렉터리 (/home/nano/beacon/ 아래):

```
SPEC_NET.md
server/beacon_server.py
server/store.py
server/policy.py
server/config.example.json
server/tests/
tools/beaconctl.py
sim/sim_nodes.py
firmware/beacon_node/
  beacon_node.ino
  config.h
  secrets.h
  rtc_bm8563.h/.cpp
  power.h/.cpp
  netproto.h/.cpp
  camera_cap.h/.cpp
  sensors.h/.cpp
results/
report.md
```

데이터: /mnt/nvme/beacon/beacon.db, 이미지 /mnt/nvme/beacon/images/<node_id>/<YYYYmmdd-HHMMSS>_<cmd_id>.jpg.

---

## 4. 노드 상태 (서버 측)

| 상태 | 진입 | 서버 next | 명령 |
|---|---|---:|---|
| DISCOVERED | 모르는 노드 첫 체크인 | 900 s | 주지 않음 |
| ATTACHED | 관리자가 attach | interval_s (기본 300, 허용 60~14400) | 큐에서 배분 |
| DETACHED | 관리자가 detach | 3600 s | 주지 않음, 큐 명령 expired |
| HIBERNATING | hibernate 후 노드 확인 | 없음 | 타이머 없이 꺼짐 |

attach/detach가 연결/해제다. DETACHED도 1시간마다 체크인하므로 attach 후 다음 체크인에서 사용할 수 있다. 물리 회수에는 hibernate를 쓴다.

ATTACHED 주기 순서:
1. 세션 요청이면 next와 hold(최대 180).
2. watch_until>now이면 next=60.
3. vbat_mv<3300이면 next=14400, 이미지 명령 failed(low_battery).
4. vbat_mv<3450이면 next=min(interval_s×4,14400), 이미지 명령 failed(low_battery).
5. 그 외 interval_s.

전압 임계값은 리튬이온 일반값 가정이다. 모든 next에 ±10% 균일 지터 적용 후 [30,15300]으로 자른다. 15300 s는 BM8563 최대 255분이다. 온라인은 now>last_seen+next_given×1.5+60이면 offline으로 표시하며 상태는 변경하지 않는다.

---

## 5. 프로토콜 v1

### 5.1 공통

- 노드 포트 0.0.0.0:8080, 관리 127.0.0.1:8081.
- 모든 노드 요청에 X-Node-Id: tc-<eFuse MAC 하위 3바이트 hex 소문자>.
- ATTACHED가 되면 서버가 다음 체크인에 tok=<32 hex>를 1회 보내고 노드는 NVS에 저장, 이후 X-Token 사용(TOFU). 저장 토큰과 다른 토큰이면 401. 노드는 401에서 토큰을 지우고 tokenless 체크인으로 복구하며, 서버가 DB를 초기화한 경우 DISCOVERED가 되어 재 attach 필요.
- 인증은 같은 LAN의 오작동 방지 수준이다. 평문 HTTP이며 공유기 8080을 외부 공개하지 않는다.
- 노드 HTTP 연결 3 s, 응답 5 s, 롱폴 wait+5 s. 본문 최대 2 KB, 체크인당 명령 최대 4개.

### 5.2 POST /api/v1/checkin

노드 JSON 본문 예:

```json
{"v":1,"fw":"beacon-0.1.0","boot":"rtc","seq":1234,
 "vbat_mv":3980,"rssi":-55,"ch":6,
 "t":{"wifi_ms":640,"fast":1,"prev_awake_ms":2100,"prev_result":"ok"}}
```

boot는 rtc(BM8563 타이머), cold(배터리 장착/USB), deepsleep(USB 대체 경로), wdt, other다. seq는 NVS 카운터로 깨어날 때 증가한다. prev_awake_ms/prev_result는 직전 활성시간과 결과(ok|wifi_fail|http_fail|awake_cap|rtc_fail)다.

text/plain 응답:

```
v=1
next=300
tok=9f2c...          (발급할 때만)
hold=0
cmd=17 sensor
cmd=18 image fs=VGA q=12 warm=500
end
```

각 줄은 key=value, cmd 줄은 cmd=<id> <type> [k=v ...]. 모르는 키는 무시. 마지막 줄이 end가 아니면 잘린 응답으로 간주해 명령을 버리고 next는 저장된 이전 값(없으면 300). next는 [30,15300] 범위. HTTP 200이 아니면 체크인 실패.

### 5.3 POST /api/v1/result?cmd=<id>

- 센서: Content-Type application/json, 본문 예: {"ok":1,"sensors":[{"type":"sht30","addr":68,"t_c":21.43,"rh":63.2}]}. 센서가 없으면 {"ok":0,"err":"sensor_absent"}.
- 이미지: Content-Type image/jpeg, 본문 JPEG. X-Warm-Ms(init부터 촬영까지 ms), X-Init-Ms(init 소요), X-Fs, X-Q 헤더.
- 실패: Content-Type application/json, {"ok":0,"err":"camera_init 0x105"}.
- 첫 결과 200 ok, 이미 받은 cmd_id는 200 dup, 모르는 cmd_id 또는 다른 노드 명령은 404.

### 5.4 GET /api/v1/poll?wait=20

체크인 hold>0일 때만 쓴다. 명령 발생 또는 wait 만료까지 보류한다. 응답 형식은 체크인과 같고 hold=남은 초를 포함한다. 서버는 hold=0으로 세션을 끝낼 수 있다. 노드는 hold>0이고 자체 180초 상한 내에서 반복 폴링하고 명령을 즉시 실행·업로드한다.

### 5.5 명령

| type | 인자 | 동작 |
|---|---|---|
| sensor | 없음 | Grove 버스의 SHT30(0x44,0x45), DHT20(0x38)을 찾아 모두 읽음 |
| image | fs(QVGA|VGA|SVGA|XGA|HD|SXGA|UXGA, 기본 VGA), q(4~40, 기본 12), warm(ms, 기본 500, 최대 3000) | 카메라 init→warm 동안 프레임 버림→촬영→업로드 |
| config | interval, fast(0/1) 등 | NVS 설정 갱신(현재 fast만) |
| hibernate | 없음 | 결과 {"ok":1} 업로드 후 타이머 없이 전원 차단 |

jpeg_buffer_size=max(128 KiB, 폭×높이/3). cam_test에서 VGA 기본 61,440 B 버퍼로 FB-OVF가 났기 때문이다.

### 5.6 전달과 만료

queued→dispatched→done|failed|expired. 배분은 queued 또는 dispatched_at으로부터 120 s가 지나고 attempts<3인 것. id 오름차순, 최대 4개. 배분마다 attempts++. 3회 배분 후 결과 없으면 failed(no_result). 기본 expires_at=created_at+max(2×next_given,900 s). 결과 테이블 cmd_id UNIQUE.

### 5.7 시퀀스 예

```
관리자 beaconctl image tc-a1b2c3 → commands#18 queued
다음 체크인(최대 T초)에서 노드가 명령 수신
POST /api/v1/result?cmd=18 (image/jpeg) → 200 ok
노드는 BM8563 300 s 설정, Wi-Fi off, GPIO33 LOW
```

---

## 6. 노드 펌웨어

외부 라이브러리를 쓰지 않는다. 코어 내장 WiFi, HTTPClient, Preferences, Wire, esp_camera만 사용한다. secrets.h가 없으면 #error.

### 6.1 부팅 순서

1. pinMode(33,OUTPUT); digitalWrite(33,HIGH)를 가장 먼저 실행.
2. t_boot=millis()를 기록하고 활성 상한 타이머 시작(6.8).
3. Serial.begin(115200). 로그는 짧고 비밀정보 금지.
4. Wire1(SDA=12,SCL=14)로 RTC 버스를 열고 BM8563 Control_status_2(0x01)의 TF(bit2)로 boot 원인을 정한 뒤 TF/TIE를 지운다.
5. NVS Preferences 네임스페이스 beacon을 읽는다.
6. 배터리 전압 측정(6.7).
7. Wi-Fi→checkin→명령→세션→전원 차단.

카메라/센서는 해당 명령이 있을 때만 초기화한다.

### 6.2 NVS 키

| 키 | 의미 | 쓰기 시점 |
|---|---|---|
| seq | 깨어남 카운터 | 매 사이클 끝 |
| next | 직전에 받은 next | 값이 바뀔 때 |
| tok | 인증 토큰 | 받을 때, 401 삭제 |
| ch,bssid | 빠른 접속 채널/BSSID | 값이 바뀔 때 |
| fail | 연속 실패 | 실패 시 증가, 성공 시 0으로 |
| prev_ms,prev_res | 직전 활성 시간/결과 | seq와 함께 사이클당 1회 |
| fast | fast 사용 여부, 기본 1 | config 명령 시 |

사이클당 NVS 쓰기 1회 목표. 300 s 주기면 하루 288회이며 wear leveling으로 문제없다는 판단은 추정이다.

### 6.3 Wi-Fi

WiFi.persistent(false), WiFi.mode(WIFI_STA), WiFi.setSleep(false). config.h USE_STATIC_IP=1이면 WiFi.config(ip,gw,mask,dns), 기본은 DHCP. fast=1이며 NVS에 ch/bssid가 있으면 WiFi.begin(ssid,pass,ch,bssid), 5 s 제한. 실패 시 일반 WiFi.begin(ssid,pass), 10 s. 성공 후 실제 채널/BSSID가 바뀐 경우에만 NVS 갱신. wifi_ms와 fast 성공 여부 보고.

### 6.4 서버 주소

config.h의 SERVER_HOST와 SERVER_PORT를 사용한다. Jetson IP는 DHCP 예약으로 고정(사람 작업). mDNS 금지.

### 6.5 power_off(next_s)

1. WiFi.disconnect(true), WiFi.mode(WIFI_OFF).
2. NVS 사이클 기록 커밋.
3. BM8563 타이머(PCF8563 호환 레지스터, M5 TimerCam 라이브러리와 대조):
   - TF/TIE를 지우고 타이머 정지(0x0E TE=0).
   - next_s≤255면 1 Hz(TD=10), 그 외 1/60 Hz(TD=11), round(next_s/60)를 [1,255]로 제한.
   - 0x0F 값, 0x0E TE=1 및 TD, 0x01 TIE=1(TI_TP=0).
   - 세 레지스터 재읽기 일치 확인, 최대 3회 재시도. 계속 실패하면 prev_res=rtc_fail 및 7절 대체 경로.
4. digitalWrite(33,LOW) 후 1000 ms 대기.
5. 여전히 실행 중이면 USB 전원으로 판단한다. esp_sleep_enable_timer_wakeup(next_s×10^6), esp_deep_sleep_start. 깨어나면 boot=deepsleep.
6. hibernate 때는 타이머 설정하지 않고 TIE=0. USB면 wake source 없이 deep sleep.

타이머 설정 실패 상태에서 전원이 끊기면 재투입 전 깨어나지 못할 수 있으므로 검증 생략 금지. 첫 타이머 주기는 최대 1틱 짧을 수 있다.

### 6.6 실패 처리

Wi-Fi 실패는 fail++ 후 next=min(next_saved×2^min(fail,3),3600). 체크인 실패(연결 거부/timeout/비200/잘린 응답)도 같은 백오프. 401은 tok 삭제 후 next_saved로 종료. 결과 업로드는 1회 재시도 후 포기한다.

### 6.7 배터리

analogReadMilliVolts(38)×VBAT_SCALE. config.h 기본값 2.0은 확인되지 않았다. 8회 평균. 사람은 멀티미터로 배터리 전압을 측정해 보정한다.

### 6.8 깨어 있는 시간 상한

일반 25 s, 세션 180 s. esp_timer 일회성 콜백. 만료 시 prev_res=awake_cap 후 power_off(next_saved). 콜백은 직접 긴 처리를 하지 않고 플래그/태스크 사용. 서버 무응답과 정지로 배터리를 소모하지 않게 하는 마지막 장치다.

### 6.9 단계 시간

wifi_ms, checkin_http_ms, cam_init_ms, warm_ms, upload_ms, prev_awake_ms를 millis()로 측정해 다음 checkin 또는 결과 헤더에 보낸다.

### 6.10 카메라

cam_test 핀맵 그대로: PWDN -1, RESET 15, XCLK 27, SIOD 25, SIOC 23, D0 32, D1 35, D2 34, D3 5, D4 39, D5 18, D6 36, D7 19, VSYNC 22, HREF 26, PCLK 21. fb_location=PSRAM, fb_count=1, CAMERA_GRAB_LATEST, jpeg_buffer_size는 5.5절. init 실패 코드 업로드, 재시도 금지. 촬영 후 esp_camera_deinit().

### 6.11 센서

Wire(SDA=4,SCL=13,100 kHz)에서 0x44,0x45,0x38 확인. SHT30은 0x24 0x00, 16 ms, 6바이트, CRC-8(poly 0x31, init 0xFF). DHT20은 전원 후 100 ms, status 0x71 bit3 보정 완료, 0xAC 0x33 0x00, 80 ms, 7바이트와 CRC. 센서 미연결 1차 시험은 sensor_absent. Grove 5V와 풀업은 사람이 멀티미터로 확인 후 연결.

---

## 7. 서버

Python 3.10 표준 라이브러리(http.server.ThreadingHTTPServer, sqlite3, json, threading, secrets)만 사용한다. 노드 :8080과 관리 127.0.0.1:8081을 한 프로세스 두 스레드로 띄운다. SQLite WAL, 단일 잠금으로 쓰기 직렬화. 롱폴은 노드별 threading.Condition. config.json에 포트, 경로, 주기, 임계값, test_mode를 둔다(test_mode 최소 next 5 s). 로그는 시간/노드/요청/결과/ms 한 줄 요약, 토큰 앞 4자만.

### 7.1 SQLite 스키마

```sql
CREATE TABLE nodes(
  id TEXT PRIMARY KEY, label TEXT, state TEXT NOT NULL,
  token TEXT, token_sent INTEGER DEFAULT 0,
  interval_s INTEGER DEFAULT 300, watch_until REAL, session_req_s INTEGER DEFAULT 0,
  first_seen REAL, last_seen REAL, next_given INTEGER,
  last_ip TEXT, last_rssi INTEGER, last_vbat_mv INTEGER, last_seq INTEGER, fw TEXT);
CREATE TABLE commands(
  id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL, type TEXT NOT NULL,
  params TEXT, state TEXT NOT NULL, reason TEXT,
  created_at REAL, dispatched_at REAL, attempts INTEGER DEFAULT 0,
  done_at REAL, expires_at REAL);
CREATE TABLE readings(
  id INTEGER PRIMARY KEY, node_id TEXT, cmd_id INTEGER UNIQUE, received_at REAL, body TEXT);
CREATE TABLE images(
  id INTEGER PRIMARY KEY, node_id TEXT, cmd_id INTEGER UNIQUE, received_at REAL,
  path TEXT, bytes INTEGER, width INTEGER, height INTEGER, warm_ms INTEGER);
CREATE TABLE checkins(
  id INTEGER PRIMARY KEY, node_id TEXT, received_at REAL, seq INTEGER, boot TEXT,
  vbat_mv INTEGER, rssi INTEGER, wifi_ms INTEGER, fast INTEGER,
  prev_awake_ms INTEGER, prev_result TEXT, next_given INTEGER);
```

이미지는 저장 전 SOI(FFD8)/EOI(FFD9), SOF0/SOF2에서 폭/높이를 확인한다(Pillow 없이).

### 7.2 관리 API (127.0.0.1:8081, JSON)

| 메서드·경로 | 동작 |
|---|---|
| GET /admin/nodes | 전체 노드, 상태, online/offline, 마지막 값 |
| POST /admin/nodes/{id}/attach {label?,interval_s?} | ATTACHED, 다음 체크인용 토큰 생성 |
| POST /admin/nodes/{id}/detach | DETACHED, 대기 명령 만료 |
| POST /admin/nodes/{id}/hibernate | hibernate 명령, 결과 수신 후 HIBERNATING |
| POST /admin/nodes/{id}/interval {interval_s} | 주기 변경 |
| POST /admin/nodes/{id}/watch {minutes} | 최대 30분 watch_until |
| POST /admin/nodes/{id}/session {hold_s} | 최대 180초 hold 요청 |
| POST /admin/nodes/{id}/commands {type,params} | 명령 생성, ATTACHED가 아니면 409 |
| GET /admin/commands/{cmd_id} | 상태/결과 |
| GET /admin/commands/{cmd_id}/wait?timeout=600 | 완료 대기 |
| GET /admin/nodes/{id}/energy | 기록 및 13절 상수 기반 추정 |

### 7.3 CLI

tools/beaconctl.py 명령: nodes, attach <id> [--label L] [--interval S], detach <id>, hibernate <id>, interval <id> S, watch <id> --minutes M, session <id> --hold S, sensor <id> [--wait], image <id> [--fs VGA --q 12 --warm 500] [--wait], cmd <cmd_id>, energy <id>.

---

## 8. 시뮬레이터

sim/sim_nodes.py는 --n 20 --server http://127.0.0.1:8080 --duration 300 --seed 1 지원. 가상 노드는 프로토콜을 따르고 test_mode에서 next만큼 잔다. 장애 주입: Wi-Fi 실패 5%, 업로드 유실 10%, 잘린 응답 2%, 롱폴 끊김 2%. 유효한 작은 내장 JPEG와 센서 난수를 사용한다. 끝나면 DB 검증으로 AC 판정해 results/sim_report.json에 쓴다.

---

## 9. 금지와 안전 규칙

- secrets.h를 읽거나 출력/수정하지 않는다(cat/head/편집기 금지). 존재 여부 및 grep -q 'YOUR_'만 허용. 없으면 WIFI_SSID/WIFI_PASS 템플릿만 생성하고 중단.
- 쓰기는 /home/nano/beacon/, /mnt/nvme/beacon/, 시스템 임시 폴더만 허용.
- /dev 접근, esptool 직접 호출, erase_flash, 업로드 금지. 사람만 업로드.
- sudo, apt, 권한/시스템 설정 변경, systemd 등록 금지.
- 서버를 백그라운드로 남기지 않는다. 모든 외부 명령에 timeout.
- 핀과 GPIO33 순서를 바꾸지 않는다.
- 성공을 추측하지 않는다. 명령, 종료 코드, 로그 근거로 보고한다.

---

## 10. 절차

### N0 사전 점검 (Codex, 게이트)

각각 따로 실행한다:

```bash
pwd
python3 --version
/home/nano/bin/arduino-cli core list
df -h /mnt/nvme
test -f firmware/beacon_node/secrets.h && echo SECRETS_PRESENT || echo SECRETS_MISSING
grep -q 'YOUR_' firmware/beacon_node/secrets.h && echo PLACEHOLDER_REMAINS || echo PLACEHOLDER_OK
timeout 5 python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print('LOOPBACK_OK')"
```

루프백이 막히면 N1/N2 서버시험은 사람이 실행하도록 스크립트만 만든다.

### N1 서버와 단위시험

server/ 및 tools/ 작성 후 python3 -m unittest discover -s server/tests -v. 시험: 상태 전이, 4절 주기 결정/지터, 배분/재배분, 3회 후 failed, 만료, 중복 결과 dup, 401, 잘린 요청, 롱폴 알림/timeout, JPEG 파싱.

### N2 시뮬레이터 통합시험

test_mode 서버와 노드 20대, 300초. 관리 API attach/detach/명령/session 섞기. 서버 종료 및 종료 확인 후 판정한다.

### N3 펌웨어 컴파일

```bash
/home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 \
  --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node 2>&1 | tee results/compile.log
```

오류는 소스만 최대 3회 고쳐 재시도한다. 앱 영역 초과(text section exceeds available space in board)일 때 PartitionScheme=huge_app 추가를 1회 허용하며 변경 기록. 매 회 오류/수정 기록. 성공 시 flash/RAM 사용량 기록. 시스템 임시 폴더나 데이터 폴더 쓰기 권한 실패면 보고 후 중단한다.

firmware/flash.sh 작성. cam_test의 flash.sh와 같은 흐름. monitor는 -c dtr=off -c rts=off 및 timeout -s INT -k 3을 사용한다.

### N4 실기시험 (사람+Codex)

사람이 서버를 실행하고(python3 server/beacon_server.py --config server/config.json) firmware/flash.sh로 업로드한다. 처음은 USB 전원, 다음은 배터리 전원.

| ID | 절차 | 기대 |
|---|---|---|
| R1 | 업로드 후 체크인 | DISCOVERED, next≈900 |
| R2 | attach, interval 60 | 다음 체크인 tok 발급, 이후 X-Token |
| R3 | sensor --wait | 센서 미연결이면 sensor_absent, 결과 시간≤주기+10 s |
| R4 | image --wait | 유효 JPEG, X-Warm-Ms≥500 |
| R5 | session --hold 60 후 이미지 3회 | 요청 지연 각각≤3 s |
| R6 | 서버 종료 후 2주기 | 노드 25 s 안에 꺼짐, 백오프 증가(시리얼) |
| R7 | detach | next≈3600, 명령 거부(409) |
| R8 | 배터리 전원 차단 | 사람이 사이클 사이 µA 측정 |
| R9 | 배터리 RTC 기상 | boot=rtc 연속 3회 이상 |

### N5 보고

report.md에 AC1~AC9, 13절 값 반영 여부 및 에너지 표 재계산을 기록한다.

---

## 11. 수락 기준

| ID | 기준 |
|---|---|
| AC1 | 단위시험 전부 통과 |
| AC2 | ATTACHED 명령의 만료 전 처리율≥99%, 결과 중복 0 |
| AC3 | DETACHED/DISCOVERED 명령 배분 0 |
| AC4 | 서버 next가 정책값 ±10% 안 |
| AC5 | 펌웨어 컴파일 0, flash/RAM 기록 |
| AC6 | 실기 R1~R7 |
| AC7 | 실기 R8/R9(사람 측정) |
| AC8 | 명령 없는 정상 사이클 prev_awake_ms 중앙값 및 fast 경로 성공률 |
| AC9 | 실패 시나리오에서도 활성 시간≤25 s(세션≤180 s) |

---

## 12. 노드 사이클 상태도

```
POWER_ON ─ GPIO33 HIGH ─ RTC TF 확인/해제 ─ NVS 읽기 ─ VBAT
  └→ WIFI_CONNECT ─실패→ BACKOFF
       └성공→ CHECKIN ─실패/401→ BACKOFF
                 └200→ 명령(센서/이미지/설정)→결과 업로드
                          └ hold>0 ? SESSION(롱폴 반복, ≤180 s)
→ POWER_OFF: Wi-Fi off → NVS 커밋 → RTC 설정·검증
             → GPIO33 LOW → (계속 실행 시) deep sleep
전 구간 상한: 일반 25 s / 세션 180 s
```

---

## 13. 사람이 측정해야 할 값

| 값 | 방법 | 사용처 |
|---|---|---|
| I_off | 배터리 +극 직렬 멀티미터(µA 범위, 기상 시 mA부터) | 에너지 모델 |
| 활성 평균 전류 | mA 측정 또는 USB 전류계/로거 | E_c/E_img |
| VBAT_SCALE | 실측 배터리 전압÷GPIO38 analogReadMilliVolts 평균 | 6.7 |
| 카메라 warm | cam_test v2.1 t_conv 실측 | 5.5 기본값 |
| 충전 모듈 역전류 | USB 제거 후 TP4056 B+ 전류 | I_off |
| Grove 5V | 보드 off 시 5V 전압 | 센서 대기전류 |

측정치는 server/config.json의 energy 항목 i_active_ma, i_cam_ma, i_off_ua, usable_mah에 반영해 energy 계산한다.

---

## 14. 실패 처리

단계별 재시도는 명시 횟수만 한다. 중단 시 실패 단계, 정확한 명령, 종료 코드, 로그 마지막 30줄, 원인 가설(가설임을 표시), 사람이 할 조치를 보고한다. 중단 시 산출물과 로그는 삭제하지 않는다.

---

## 15. 보고 형식 (report.md)

1. 환경(버전, FQBN, 서버 설정).
2. 단계 표(단계, 담당, 명령, 종료 코드, 결과 한 줄).
3. 단위시험 및 시뮬레이션 AC1~AC4 수치.
4. 컴파일 사용량.
5. 실기 R1~R9, 노드 wifi_ms/prev_awake_ms 분포.
6. 13절 측정과 2.4절 에너지 표 재계산.
7. 실패·경고·가정. 추론은 “추정”이라고 표시한다.

변경 이력: 2026-11-09 네트워크 172.30.1.0/24로 변경
변경 이력: 2026-11-10 네트워크 192.168.25.0/24로 변경

