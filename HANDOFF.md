# 사람 작업 안내

N1 단위시험(21/21)과 N2 시뮬레이션(AC2~AC4)이 사람 실행으로 통과했습니다. 최신 RTC 첫 주기 readback 수정 펌웨어는 컴파일됐지만 보드 업로드와 RTC 기상은 아직 확인되지 않았습니다.

1. Wi-Fi 설정은 파일 값을 출력하지 말고 직접 확인합니다. 배터리 케이블을 분리하고 Timer Camera 렌즈 앞을 정리합니다.
2. N1/N2는 이미 통과했습니다. 서버 설정 파일이 없으면 `server/config.example.json`을 `server/config.json`으로 복사합니다. 서버를 실행합니다:
   `cd /home/nano/beacon && python3 server/beacon_server.py --config server/config.json`
3. 다른 터미널에서 USB 전원으로 보드를 연결하고 최신 펌웨어를 업로드합니다:
   `bash /home/nano/beacon/firmware/flash.sh`
   `upload exit=0`을 확인합니다. 시리얼 자동 캡처가 비어 있으면 직접 모니터를 열어 확인합니다:
   `timeout -s INT -k 3 25 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off`
   `Connecting to /dev/ttyUSB0`가 표시된 뒤 RESET 버튼을 한 번 누릅니다. `RTC_TIMER armed=1` 및 `POWER_OFF ... rtc_timer=1`을 확인합니다. 업로드 실패 시 `results/upload.log` 마지막 30줄을 Codex에게 전달합니다.
4. RTC 타이머 arm이 확인된 다음에만 배터리 단독 시험을 진행합니다. 체크인 로그에 `commands=0`이면 촬영/업로드 명령이 없었던 것입니다. 이미지를 시험하려면 노드를 `attach`한 뒤 `image` 명령을 큐에 넣고 다음 체크인을 기다립니다.
5. Codex에게 새 시리얼 로그와 실기 결과를 알립니다. 이후 R1~R9와 13절의 전원 측정을 진행합니다.

## 이미지 요청 CLI

`tools/beaconctl.py`에 `image <node_id> [--fs VGA --q 12 --warm 500] [--wait]` 명령이 있습니다. 요청은 카메라에서 연속 전송하는 방식이 아니라 서버 큐에 등록되며, 노드의 다음 체크인 때 촬영·업로드합니다.

이미지 CLI는 서버에 명령을 등록하고 다음 체크인에 전달합니다. 최신 시리얼 로그에서 카메라 오류 원인은 확인됐습니다. RTC가 `Wire1`(I2C controller 1)을 계속 점유했고 esp_camera SCCB가 같은 controller를 사용하려 해 `ESP_ERR_INVALID_STATE (0x103)`가 났습니다. 펌웨어는 RTC 읽기 직후 `Wire1.end()`를 호출하고 종료 전 타이머 설정 때 버스를 다시 엽니다. `results/compile_i2c_bus_fix.log`의 컴파일은 성공했지만 새 펌웨어는 아직 보드에 올리지 않았고 사진 수신도 확인되지 않았습니다.

카메라 수정 확인 순서:
1. 서버를 실행한 상태에서 `bash /home/nano/beacon/firmware/flash.sh`로 새 빌드를 업로드합니다. 시리얼에서 `RTC I2C released_for_camera=1`을 확인합니다.
2. 관리 API가 동작하는 별도 터미널에서 `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py image tc-004f8c --fs VGA --q 12 --warm 500`을 실행해 이미지 명령 하나만 큐에 넣습니다.
3. USB 전원 상태에서 별도 터미널로 `timeout -s INT -k 3 90 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off`를 열고, RTC 체크인 때까지 기다립니다. `CHECKIN ... commands=1` 뒤에 `i2c.common` 오류가 더는 없는지, `RESULT`가 성공했는지 확인합니다. 포트는 monitor 한 프로세스만 열어야 합니다.
4. 명령 ID로 `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py cmd <cmd_id>`를 조회합니다. `done`이고 결과가 이미지이면 수신 성공입니다. 여전히 `camera_init` 오류면 그 시리얼 구간 전체를 Codex에게 전달하고, 추가 이미지 명령은 등록하지 않습니다.

## Wi-Fi 네트워크 변경

새 네트워크의 SSID/비밀번호와 Jetson Wi-Fi 주소를 ESP32 펌웨어에 반영하려면 Jetson 셸에서 다음을 실행합니다:

1. `timeout 5 ip -4 -o addr show`로 Wi-Fi 인터페이스의 현재 IPv4 주소를 확인합니다. 유선 관리 링크 주소가 아니라 노드와 같은 LAN에 연결된 Wi-Fi 주소를 사용합니다.
2. 이번 주소가 유지 중이면 `python3 /home/nano/beacon/tools/beacon_wifi.py --server-host 192.168.219.123`을 실행합니다. `--server-host`에는 SSID가 아니라 Jetson의 Wi-Fi IPv4를 넣습니다. 기존 Wi-Fi 설정 교체를 확인한 뒤 SSID와 비밀번호를 입력합니다. 비밀번호는 입력 중 표시되지 않습니다. ESP32 Timer Camera는 2.4 GHz만 지원합니다. `U+Net5694_5G`처럼 이름이 5 GHz를 가리키면, 같은 SSID가 2.4 GHz에서도 제공되는지 확인 질문에 답하고, 아니라면 2.4 GHz SSID를 선택합니다. 이 도구는 `secrets.h`와 `config.h`를 갱신하고 컴파일하며, 결과 로그는 `results/wifi_rebuild.log`에 저장합니다. 자격정보는 Codex가 읽거나 출력하지 않습니다.
3. 컴파일 성공 후 USB 연결된 보드에 `bash /home/nano/beacon/firmware/flash.sh`를 실행해 업로드합니다. 이 단계는 사람이 실행합니다.
4. 노드 서버가 실행 중인 별도 터미널에서 `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes`를 실행합니다. 새 `last_ip`, `last_seen`, `online` 값을 확인합니다. 현재 Codex 확인 시점에는 `server/config.json`은 있지만 관리 API `127.0.0.1:8081`은 연결 거부였습니다. 서버가 꺼져 있으면 사람 셸에서 `timeout 3600 python3 /home/nano/beacon/server/beacon_server.py --config /home/nano/beacon/server/config.json`로 실행합니다.

최신 부팅 로그가 `WIFI failed status=1`이면 설치 코어 기준 `WL_NO_SSID_AVAIL`(SSID/AP를 찾지 못함)입니다. ESP32 Timer Camera는 2.4 GHz만 지원합니다. 사용 가능한 2.4 GHz SSID로 `beacon_wifi.py`를 다시 실행하고 컴파일 후 업로드해야 합니다. 이번 실패에서는 RTC 타이머는 `rtc_timer=1`로 arm됐지만 Wi-Fi 재시도는 3600초 뒤로 예약됐으므로, 새 펌웨어 업로드 후 직접 모니터를 열어 RESET을 눌러 즉시 재시도합니다.

Wi-Fi 실패 재시도는 현재 테스트 빌드에서 5초로 임시 단축했고 컴파일은 성공했습니다. 적용하려면 새 빌드를 `firmware/flash.sh`로 업로드해야 합니다. 네트워크 확인 뒤 운영용 지수 백오프로 복구합니다.

통신 관리 명령은 `python3 /home/nano/beacon/tools/beaconctl.py nodes`, `attach <node_id> --interval 60`, `image <node_id> --fs VGA --q 12 --warm 500`, `cmd <cmd_id>`입니다. `image`는 명령을 큐에 등록하고 노드의 다음 체크인 때 전달합니다. 이번 수정 펌웨어를 업로드하기 전에는 이미지 명령을 등록하지 않습니다.

N1/N2 실패 시 로그를 보존하고 원인을 수정한 뒤 재실행합니다. 수정-실행 반복은 최대 3회입니다. Pillow나 외부 패키지는 필요하지 않습니다.

## USB 직접 하드웨어 진단

USB 진단 전용 빌드는 `results/usb_diag_compile.log`에 컴파일 결과가 있으며 현재 `firmware/build` 산출물이 진단 모드입니다. 이 빌드는 Beacon 서버에 접속하지 않고, 서버 명령 없이 시리얼에서 센서와 보드 상태를 읽습니다. USB 전원으로만 사용하고 배터리 케이블은 분리합니다. 진단 콘솔은 15분 뒤 deep sleep합니다.

1. 사람이 `bash /home/nano/beacon/firmware/flash.sh`로 진단 빌드를 업로드합니다.
2. 다른 모니터가 닫힌 상태에서 직접 시리얼을 엽니다: `timeout -s INT -k 3 180 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off`.
3. `USB_DIAG_READY`와 `usb-diag>` 프롬프트가 나오면 입력 후 Enter를 누릅니다. `help`는 명령 목록, `status`는 RTC/NVS/ADC/heap/Wi-Fi 상태, `i2c`는 Grove 두 핀 순서와 RTC/카메라 SCCB 버스 스캔, `sensor`는 두 Grove 핀 순서를 각각 시험하며 idle line level·raw 바이트·CRC·변환값을 출력합니다. `camera`는 로컬 VGA 캡처, `wifi`는 서버 요청 없이 AP 연결 정보, `all`은 전체 점검입니다. SSID/비밀번호/token 값은 출력하지 않습니다.
4. 기본 배선은 G4=SDA/G13=SCL입니다. SHT30은 `SENSOR_WIRING_TEST orientation=G4_SDA_G13_SCL`에서 0x44 또는 0x45 ACK, CRC 정상, 온도·습도 값이 나오면 읽기 성공입니다. 반대 순서 시험은 배선을 진단하기 위한 것이며, 운영 펌웨어 핀맵은 바꾸지 않습니다. 두 순서 모두 주소 응답이 없으면 센서 전원·GND·선 연결을 확인합니다.
5. 정상 비콘 운용으로 복귀할 때는 진단 macro 없이 일반 컴파일을 다시 하고 사람이 업로드합니다: `/home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node` 후 `bash /home/nano/beacon/firmware/flash.sh`.

