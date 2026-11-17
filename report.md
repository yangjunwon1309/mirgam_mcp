# SPEC_NET 진행 보고서

## 환경

- 호스트: /home/nano/beacon, Python 3.10.12, arduino-cli 코어 esp32:esp32 3.3.12.
- FQBN: `esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000`.
- 네트워크: 사용자 확인값은 wlP1p1s0 `192.168.25.19/24`, 게이트웨이 `192.168.25.1`; 노드 시리얼 주소는 `192.168.25.45`. 같은 서브넷으로 확인됨. enP8p1s0 `192.168.137.152`는 관리 링크이며 노드 통신에 사용하지 않음. 펌웨어 `SERVER_HOST=192.168.25.19`, DHCP, `USE_STATIC_IP=0`.
- /mnt/nvme 가용 공간: 421 GB.
- secrets.h는 출력하지 않았으며 존재 확인 및 `grep -q 'YOUR_'`만 수행했습니다.
- 네트워크 인터페이스 주소는 사용자가 제공한 사실을 반영했습니다. Codex는 netlink 및 loopback bind를 사용할 수 없습니다.

## 단계별 실행 기록

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| N0 | Codex | `pwd` | 0 | /home/nano/beacon |
| N0 | Codex | `python3 --version` | 0 | Python 3.10.12 |
| N0 | Codex | `/home/nano/bin/arduino-cli core list` | 0 | esp32:esp32 3.3.12 |
| N0 | Codex | `df -h /mnt/nvme` | 0 | 421 GB 여유 |
| N0 | Codex | `test -f firmware/beacon_node/secrets.h && echo SECRETS_PRESENT || echo SECRETS_MISSING` | 0 | SECRETS_PRESENT |
| N0 | Codex | `grep -q 'YOUR_' firmware/beacon_node/secrets.h && echo PLACEHOLDER_REMAINS || echo PLACEHOLDER_OK` | 0 | PLACEHOLDER_OK |
| N0 | Codex | `timeout 5 python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print("LOOPBACK_OK")'` | 1 | PermissionError: Operation not permitted. N1/N2 실행을 사람에게 위임 |
| A 정적검사 | Codex | `timeout 60 python3 -m py_compile server/beacon_server.py server/store.py server/policy.py tools/beaconctl.py sim/sim_nodes.py sim/verify_sim.py server/tests/test_policy.py server/tests/test_store.py server/tests/test_http.py` | 0 | Python 정적 문법 검사 통과 |
| A 스크립트 | Codex | `timeout 10 bash -n tools/run_n1.sh tools/run_n2.sh firmware/flash.sh` | 0 | bash 문법 검사 통과 |
| N1 | 사람 | `bash /home/nano/beacon/tools/run_n1.sh` | 0 | 사용자 제공: 21/21 통과 |
| N2 | 사람 | `bash /home/nano/beacon/tools/run_n2.sh` | 0 | 사용자 제공: 명령 24/24 처리, AC2~AC4 PASS, 서버 종료 확인 |
| N3 샌드박스 제한 | Codex | 아래 N3 컴파일 명령 | 1 | `/home/nano/.cache/arduino/sketches` 생성 거부. 승인 후 재시도; 이 실행은 소스 오류 재시도 횟수에 포함하지 않음 |
| N3 소스 시도 1 | Codex | 아래 N3 컴파일 명령 | 1 | `esp_reset_reason.h` 헤더 없음. `esp_system.h`로 교체 |
| N3 소스 시도 2 | Codex | 아래 N3 컴파일 명령 | 1 | `max(unsigned int,uint32_t)` 타입 불일치. 인자 타입 통일 |
| N3 소스 시도 3 | Codex | 아래 N3 컴파일 명령, 출력 `results/compile.log` | 0 | 컴파일 성공 |
| N4 업로드 1차 | 사람 | `bash /home/nano/beacon/firmware/flash.sh` | upload 0; monitor 124 | 업로드 성공. 25초 모니터 종료 후 `IP not found`; 연결/체크인 미확인 |
| N3 진단 로그 재컴파일 | Codex | `timeout 320 bash -lc 'set +e; timeout 300 /home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node 2>&1 \| timeout 310 tee /home/nano/beacon/results/compile.log; status=("${PIPESTATUS[@]}"); printf "compile exit=%s tee exit=%s\\n" "${status[0]}" "${status[1]}"; exit "${status[0]}"'` | 0 | 비밀정보 없이 BOOT/WIFI/IP/CHECKIN/POWER_OFF 로그 추가 후 컴파일 성공 |
| A4 flash 스크립트 문법 | Codex | `timeout 10 bash -n firmware/flash.sh` | 0 | 통과 |
| N4 업로드 2차 | 사람 | `bash /home/nano/beacon/firmware/flash.sh` | upload 0; monitor 137 | 사용자 제공 로그. `serial_boot.log` 0바이트, `IP not found`; `beaconctl nodes`는 `[]` |
| N4 진단 빌드 캡처 시도 | 사람 | `bash /home/nano/beacon/firmware/flash.sh` | upload 0; monitor 124 | 사용자 제공 로그. RESET 안내 직후 눌렀지만 `IP not found`; 로그 0바이트. 안내가 모니터 시작보다 먼저 출력되는 경합 확인 |
| A4 flash 모니터 순서 수정 | Codex | `timeout 10 bash -n firmware/flash.sh` | 0 | 모니터 파이프라인 시작 후 2초 대기, 그 뒤 RESET 안내를 출력하도록 수정 |
| N4 진단 모니터 재시도 | 사람 | `bash /home/nano/beacon/firmware/flash.sh` | upload 0; monitor 124 | 사용자 제공 최신 로그. 2초 대기 안내 후 RESET, `IP not found`; `serial_boot.log` 0바이트. 물리 RESET 동작/시리얼 수신은 미확인 |
| N4 UART/네트워크/RTC 진단 | 사람 | `timeout -s INT -k 3 25 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off` | 미기록 | 사용자 제공 UART 로그: IP `192.168.25.45`, checkin HTTP `-1`, RTC timer verify 실패 |
| N3 RTC 진단 수정 컴파일 | Codex | N3 컴파일 명령, 출력 `results/compile.log` | 0 | RTC 예약 비트 정리 및 레지스터 검증 로그 추가 후 컴파일 성공 |
| 네트워크 주소 갱신 | 사용자 제공/ Codex | Jetson `ip -4 -o addr show`; `ip -4 route show` | 사용자 셸 성공 | wlP1p1s0 `192.168.25.19/24`, 게이트웨이 `192.168.25.1`; `SERVER_HOST`를 이 주소로 갱신 |
| N3 현재 네트워크 반영 컴파일 | Codex | N3 컴파일 명령, 출력 `results/compile.log` | 0 | `SERVER_HOST=192.168.25.19`로 펌웨어 재컴파일 성공 |
| N4 현재 주소 펌웨어 업로드 | 사람 | `bash /home/nano/beacon/firmware/flash.sh` | upload 0; monitor 137/124/137 | 사용자 제공 로그. 업로드/hash 검증 성공, serial log 0바이트, `IP not found`; 체크인 결과 미확인 |
| N4 네트워크 체크인 및 RTC 타이머 진단 | 사람 | `timeout -s INT -k 3 25 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off` | 미기록 | 사용자가 제공한 출력에서 IP `192.168.25.45`, `CHECKIN ok next_s=958`, `commands=0`; RTC readback는 요청 16틱 대신 15틱으로 RTC 검증 실패 |
| N4 관리 CLI 노드 조회 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes` | 0 | 관리 API 응답에서 `tc-004f8c`를 확인. 초기 상태 `DISCOVERED`, `online` |
| N4 관리 CLI attach | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py attach tc-004f8c --interval 60` | 0 | 노드를 `ATTACHED`, 주기 60초로 설정. 서버 응답의 `next_given=842`는 다음 체크인 전까지 기존 값 |
| N4 관리 CLI 이미지 요청 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py image tc-004f8c --fs VGA --q 12 --warm 500` | 0 | `cmd_id=1`, `state=queued`; 서버에 이미지 명령 등록 확인 |
| N4 관리 CLI 명령 확인(초기) | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py cmd 1` | 0 | 첫 조회 때 `queued`, `attempts=0` |
| N4 다음 주기 체크인 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes` | 0 | 자동 RTC 기상 후 `last_seq=32`, `next_given=61`, 상태 `ATTACHED` 확인 |
| N4 이미지 명령 1 결과 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py cmd 1` | 1 | 서버가 명령을 배분했으나 `failed(camera_init 0x103)` 결과 수신 |
| N4 이미지 명령 2 결과 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py cmd 2` | 1 | 중복 큐 명령도 배분되어 `failed(camera_init 0x103)`; JPEG 업로드 없음 |
| N4 후속 주기 체크인 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes` | 0 | `last_seq=33`, `next_given=58`, 상태 `ATTACHED`; 60초 간격에 ±10% 지터 적용 확인 |
| CLI 정적 확인 | Codex | `timeout 10 python3 -m py_compile tools/beaconctl.py` | 0 | CLI Python 문법 검사 통과 |
| N3 RTC 첫 주기 허용 수정 컴파일 | Codex | `timeout 320 bash -lc 'set +e; timeout 300 /home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node 2>&1 | timeout 310 tee /home/nano/beacon/results/compile.log; status=("${PIPESTATUS[@]}"); printf "compile exit=%s tee exit=%s\n" "${status[0]}" "${status[1]}"; exit "${status[0]}"'` | 0 | 안정적인 2회 readback에서 요청 ticks 또는 ticks-1을 허용하고 RTC 플래그를 정리하도록 수정; 컴파일 성공. 플래시 1,071,665 bytes(81%), RAM 61,856 bytes(18%) |
| Jetson 8080 확인 | 사람 | `timeout 7 curl -sS -m 5 -o /dev/null -w 'HTTP %{http_code}\\n' http://192.168.25.19:8080/` | 0 | 응답 HTTP 400. Jetson 8080의 HTTP 서버까지 연결됨; node checkin은 별도 미확인 |
| A4 monitor 캡처 수정 | Codex | `timeout 10 bash -n firmware/flash.sh` | 0 | `script` PTY로 monitor를 실행해 터미널 표시와 로그 기록을 같이 하고 `Connecting to` 배너 이후 RESET을 안내 |
| 현재 네트워크 확인 | Codex | `timeout 5 ip -4 -o addr show`; `timeout 5 ip -4 route show` | 각각 1 | 두 명령 모두 `Cannot open netlink socket: Operation not permitted`; 현재 Jetson IP 확인 불가 |
| 현재 네트워크 확인 | Codex | `timeout 5 hostname -I`; 인터페이스 IPv4 ioctl 조회 | 각각 1 | 샌드박스에서 `Operation not permitted`; 주소 확인 불가 |
| 설정 대조 | Codex | `timeout 5 rg -n 'SERVER_HOST|SERVER_PORT|host|bind|node_port|admin_port|data_dir' firmware/beacon_node/config.h server/config.json server/config.example.json server/beacon_server.py` | 0 | 당시 펌웨어 host `172.30.1.74`; 노드 서버는 `0.0.0.0:8080` bind. 뒤에 host를 `192.168.25.19`로 갱신 |

N3 컴파일 명령(승인 후 성공한 실행 포함):

```bash
timeout 300 /home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node 2>&1 | tee /home/nano/beacon/results/compile.log
```

소스 시도별 로그: `results/compile_attempt1.log`, `results/compile_attempt2.log`, 최종 `results/compile.log`. 첫 샌드박스 캐시 오류는 도구 출력으로 확인했으며 별도 로그 파일에는 저장되지 않았습니다.

## 컴파일 사용량

- RTC 진단 추가 후 최신 빌드: 1,071,521 / 1,310,720 bytes (81%).
- 전역 RAM: 61,856 / 327,680 bytes (18%), 지역 변수에 265,824 bytes 남음.
- 컴파일 종료 코드 0.

## 단위시험 및 시뮬레이션

- 사용자가 제공한 `results/n1.log`: 19개 중 18개 통과, `test_jitter_and_bounds` 실패. 입력 base=100에서 구현 결과 9000, 테스트 기대 90으로 규약 불일치가 확인됐습니다.
- `jittered_next`를 `round(rng.uniform(0.9 * base, 1.1 * base))` 후 모드별 하한(일반 30, test_mode 5)과 상한 15300으로 자르도록 수정했습니다. 기존 기대값은 바꾸지 않았습니다.
- 실제 `random.Random(seed)` 1000회 성질 검사와 base=14400/base=10 경계 클램프 검사를 추가했습니다. 수정 후 시험 재실행은 하지 않았으며 사람 재실행 대기입니다.
- 사용자가 제공한 후속 N1 결과: 21개 중 `test_decide_returns_base_and_reason`만 실패. `FixedRandom(1.0)`이 새 API에서 600초 범위를 반환하지 않아 테스트 입력을 `FixedRandom(600)`으로 맞췄고, 기대 튜플은 유지했습니다.
- 사용자가 제공한 N2 결과: 24개 명령 중 0개 처리. 시뮬레이터 노드 스레드가 `self.initial_actions_done` 미정의 `AttributeError`로 종료된 것이 원인이며, `self.sim.initial_actions_done` 참조로 고쳤습니다. 이 오류가 AC2 실패의 직접 원인입니다.
- N2의 AC3/AC4는 제공된 결과에서 PASS, AC2는 FAIL이었습니다. `server wait exit=0`, 종료 후 curl 7, `NO_SERVER_LEFT`는 서버가 종료됐다는 정상 확인입니다. Ctrl+Z(TSTP) 중단 때도 서버를 정리하도록 trap을 추가했습니다.
- 후속 N1 결과: 21/21 통과(`N1 exit=0`).
- 후속 N2 결과: 명령 24개 중 16개 완료(0.6667), AC2 FAIL, AC3/AC4 PASS. 서버 로그에는 `/api/v1/result`의 HTTP 400이 반복됐습니다.
- 원인은 시뮬레이터 JPEG가 EOI `FF D9` 대신 `FF 64`로 끝나 서버의 JPEG 검사에서 이미지 명령 8개가 거부된 것입니다. 시뮬레이터에서 EOI 마커를 바로잡았습니다.
- JPEG 수정 후 사용자가 제공한 최종 N2 결과: 24/24 처리(1.0), 중복 결과 0, 비등록/해제 노드 배분 0, AC2~AC4 전부 PASS, `N2 exit=0`.
- 종료도 확인됐습니다: server wait exit=0, 종료 후 curl exit=7, `NO_SERVER_LEFT`. N2 AC2~AC4 최종 판정은 통과입니다.
- N2 로그 예정: `results/n2.log`; 최종 판정 파일: `results/sim_report.json`.
- N2는 별도 데이터베이스를 `/mnt/nvme/beacon/sim_<timestamp>/`에 만듭니다. 스크립트 종료 시 서버 종료 및 관리 API 응답 불가를 확인합니다.
- `tools/run_n2.sh`는 시작 직후 `results/n2.log`를 만들며 `/mnt/nvme/beacon` 또는 실행별 데이터 폴더 생성/쓰기 실패 시 `N2 exit=<코드> reason=data_dir`를 로그와 화면에 남기도록 보강했습니다.

## 실기 결과와 에너지

- 사람이 제공한 업로드는 모두 `upload exit=0`이었습니다. `flash.sh`가 저장한 serial log는 0바이트였지만, 별도로 실행한 `arduino-cli monitor`에서 UART 로그를 확인했습니다.
- 원인 확인: 기존 펌웨어는 Wi-Fi 연결 IP를 시리얼에 출력하지 않았습니다. 진단 빌드에는 `BOOT`, `IP`, `WIFI failed`, `CHECKIN`, `UPLOAD`, `POWER_OFF`를 출력하도록 추가했고 Wi-Fi 자격정보는 출력하지 않습니다.
- 첫 안내 순서 문제는 모니터를 먼저 시작하고 2초 뒤 안내하도록 수정했습니다. 이후 `flash.sh` 재시도 로그도 비어 있었지만, 별도 monitor 실행에서 UART 데이터가 확인되어 보드 리셋과 UART 수신은 동작합니다.
- monitor 137은 timeout이 INT를 보낸 뒤 3초 유예 후 KILL한 종료 코드입니다. monitor 124는 제한 시간에 따른 정상 timeout 종료입니다. 이후 별도 monitor에서 IP와 체크인 오류를 직접 확인했습니다.
- 현재 네트워크 설정으로 Jetson `192.168.25.19:8080`에 `curl`을 보내 HTTP 400을 받았습니다. 이는 8080의 HTTP 애플리케이션에 도달한 응답이며, 노드의 인증 포함 `/api/v1/checkin` 성공을 뜻하지는 않습니다.
- 기존 파이프 방식으로 `flash.sh`를 실행한 최신 시도도 시리얼 로그가 비었습니다. monitor가 실제 터미널처럼 동작하도록 `/usr/bin/script`의 PTY 캡처로 변경했고, 문법 검사는 통과했습니다. 이 수정은 아직 사람 셸에서 재실행하지 않았습니다.
- 사용자가 직접 연 시리얼 모니터에서 `IP=192.168.25.45`, `CHECKIN failed http=-1 elapsed_ms=3003`을 확인했습니다. 당시 펌웨어는 구 네트워크 주소 `172.30.1.74`로 요청했고, 보드는 `192.168.25.0/24`에 있어 연결할 수 없었습니다. 사용자가 제공한 최신 인터페이스 정보로 Jetson은 `192.168.25.19/24`; 펌웨어 `SERVER_HOST`를 `192.168.25.19`로 변경했습니다. Wi-Fi 자격정보 내용은 확인하거나 수정하지 않았습니다.
- 같은 로그의 `RTC available=1`은 RTC I2C 응답을 뜻하지만 `rtc_timer=0`은 타이머 설정/검증 실패입니다. 결과가 `rtc_fail`이고 `next_s=3600`으로 기록됐습니다. USB 전원에서는 ESP32 타이머 deep sleep 대체 경로를 쓰지만, 배터리 단독 시험은 RTC 타이머 기상이 확인될 때까지 보류합니다.
- PCF8563 호환 레지스터의 예약 비트 7~5/6~2를 0으로 쓰도록 정리하고, 타이머 설정 재시도별 I2C 단계와 읽은 레지스터 값을 출력하게 수정했습니다. 최신 펌웨어는 컴파일됐지만 이 수정은 아직 보드에서 시험하지 않았습니다.
- 2026-11-10 사용자가 제공한 새 UART 로그에서 보드 `192.168.25.45`가 `192.168.25.19` 서버에 접속하고 `CHECKIN ok next_s=958 hold_s=0 commands=0`을 받았습니다. 따라서 Wi-Fi와 체크인 왕복은 확인됐습니다. `commands=0`이므로 이 주기에는 이미지 명령이 없었고, 이미지 업로드도 발생하지 않았습니다.
- 관리 API를 통해 노드 `tc-004f8c`를 `ATTACHED`, 60초 주기로 바꿨습니다. attach 직후 저장된 `next_given=842`는 DISCOVERED 상태에서 받은 기존 간격입니다. 이후 자동 기상/체크인에서 `next_given=61`, 다시 다음 체크인에서 `58`초를 확인해 60초 기본 주기와 ±10% 지터가 적용됨을 확인했습니다.
- 이미지 명령 1과 사용자가 중복 제출한 명령 2는 다음 체크인에서 모두 배분됐지만 둘 다 `camera_init 0x103`으로 실패했습니다. 유효 JPEG 저장은 아직 없습니다. 핀이나 카메라 설정을 임의 변경하지 않고 원시 시리얼 카메라 초기화 로그를 받아 원인을 확인해야 합니다.
- 같은 로그에서 RTC `Control_status_2=0x01`, `Timer_control=0x83`은 설정됐지만 카운터가 `0x10` 대신 `0x0F`로 읽혀 이전 펌웨어가 `rtc_fail`로 판정했습니다. NXP PCF8563 사용자 매뉴얼은 타이머 시작이 RTC 클록과 비동기이며 첫 주기 길이가 n−1부터 n+1 틱 범위일 수 있다고 설명합니다. 그래서 검증은 카운터를 연속 두 번 읽고 값이 안정적이며 설정값 또는 설정값-1일 때만 성공하도록 수정했습니다. [NXP UM10301, §17](https://www.nxp.com/docs/en/user-guide/UM10301.pdf)
- 위 수정 펌웨어는 N3 컴파일 종료 코드 0으로 빌드됐지만 아직 사람이 보드에 업로드해 확인하지 않았습니다. 따라서 RTC timer arm과 실제 RTC 깨우기(R9)는 미확인이고, 배터리 전원 시험은 그 확인 뒤에 진행합니다. 다음 실기 로그에서 `rtc_timer=1` 및 `RTC_TIMER armed=1`을 확인해야 합니다.
- 이미지는 상시 스트리밍되지 않습니다. `ATTACHED` 노드에 관리 명령 `image`가 큐잉되고 노드가 체크인해 그 명령을 받을 때만 JPEG를 `/api/v1/result?cmd=<id>`로 한 번 업로드합니다. 명령이 없으면 체크인 후 전원을 끕니다.
- `wifi_ms`, `prev_awake_ms`, fast 경로 성공률, 전류, VBAT_SCALE, RTC 타이머 기상은 아직 측정되지 않았습니다.
- 가정값으로 에너지 표를 재계산하지 않았습니다. 사람이 13절 측정을 완료한 뒤 갱신합니다.

## 실패, 경고, 가정

- 샌드박스 loopback bind 실패가 확인되어 N1/N2는 실행하지 않았습니다. 정적 검사 통과는 실행시험 통과를 뜻하지 않습니다.
- 최초 컴파일은 샌드박스의 기본 arduino-cli cache 경로 쓰기 제한으로 실패했습니다. 사용자 승인 뒤 동일 컴파일을 진행했고 소스 오류 2건을 수정한 후 성공했습니다.
- 배터리 전류, VBAT_SCALE, BM8563의 실제 동작은 미측정입니다. 문서 기반 동작 외의 실측 결론은 없습니다.
- RTC 타이머의 첫 주기 readback 허용 수정은 NXP 자료에 근거해 컴파일했으며, 실제 보드에서 아직 재검증하지 않았습니다. 전원 차단과 RTC 기상은 사람 실측 전까지 성공으로 판정하지 않습니다.
- 172.30.1.0/24는 이전 사용자 제공값이며, 2026-11-10부터 192.168.25.0/24를 사용합니다. DHCP 예약은 아직 없습니다. 서버가 해당 인터페이스 IP로 접속 가능한지와 RTC 타이머 수정은 보드에서 재시험해야 합니다.

## 사람이 확인할 사항

초점, 이미지 방향(상하), 조명 상태, 렌즈 앞 장애물을 사람이 확인합니다. 전원 절단 전류와 RTC 반복 기상도 사람 측정이 필요합니다.

## 2026-11-15 Wi-Fi 변경 및 통신 CLI 후속

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| Wi-Fi 변경 CLI 작성 | Codex | `tools/beacon_wifi.py` 생성 | — | 터미널에서 SSID/비밀번호를 입력받고 비밀번호를 숨김 처리한다. `secrets.h` 기존 내용은 읽지 않는다. 명시 확인 후 자격정보와 `config.h`의 `SERVER_HOST`를 갱신하고 컴파일한다. 업로드는 수행하지 않음 |
| CLI 정적 문법 확인 | Codex | `timeout 10 python3 -m py_compile tools/beacon_wifi.py tools/beaconctl.py` | 0 | 통과 |
| CLI 도움말 확인 | Codex | `timeout 10 python3 -I tools/beacon_wifi.py --help` | 0 | 실행 인자 확인. 새 네트워크 자격정보가 아직 입력되지 않아 설정 변경/컴파일은 실행하지 않음 |
| 현재 노드 통신 조회 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes` | 1 | 로컬 관리 API `127.0.0.1:8081`에서 `Connection refused`; 현재 서버 실행이 확인되지 않음. 노드와 서버의 새 네트워크 통신은 아직 시험하지 않음 |

새 네트워크 적용 순서: 사용자가 현재 Wi-Fi IPv4 주소를 확인하고 `python3 /home/nano/beacon/tools/beacon_wifi.py --server-host <Jetson-Wi-Fi-IPv4>`를 실행해 SSID/비밀번호를 직접 입력, 컴파일 종료 코드 0을 확인, `firmware/flash.sh`로 업로드한 뒤 서버를 실행하고 `beaconctl.py nodes`로 `last_ip` 및 갱신된 `last_seen`을 확인한다. 이전 카메라 시험의 이미지 명령 1/2는 모두 `camera_init 0x103`으로 실패했으며 새 네트워크 적용만으로 카메라 문제가 해결된다고 가정하지 않는다.

## 2026-11-15 잘못된 `--server-host` 입력 후속

사용자 실행에서 `U+Net5694_5G`가 `--server-host` 값으로 전달됐습니다. 이 옵션은 SSID가 아니라 IPv4 주소입니다. 사용자가 확인한 현재 Jetson Wi-Fi 주소는 `192.168.219.123`; ESP32 Timer Camera는 2.4 GHz만 지원하므로 SSID가 5 GHz를 가리키면 같은 이름이 2.4 GHz에서도 제공되는지 사람이 확인해야 합니다.

`config.h`는 ASCII 파일이며 이 시도 뒤 파일 수정 시각도 변하지 않았습니다. 기존 `secrets.h` 내용은 읽지 않았고 해당 시도에서 파일이 갱신되지 않은 것으로 확인했습니다. 실제 UTF-8 오류의 발생 지점은 출력만으로 특정할 수 없습니다. 이후 CLI를 보완해 `--server-host`를 가장 먼저 검증하고 잘못된 인자면 자격정보 프롬프트 전에 종료합니다. 5 GHz처럼 보이는 SSID에는 2.4 GHz 지원 확인을 추가했습니다.

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| 잘못된 host 인자 검증 | Codex | `timeout 5 python3 -I tools/beacon_wifi.py --server-host U+Net5694_5G` | 2 | `SERVER_HOST must be a valid IPv4 address`; 자격정보를 묻거나 파일을 바꾸지 않음 |
| CLI 수정 문법 검사 | Codex | `timeout 10 python3 -m py_compile tools/beacon_wifi.py` | 0 | 통과 |
| CLI 수정 도움말 | Codex | `timeout 10 python3 -I tools/beacon_wifi.py --help` | 0 | 현재 IPv4를 `--server-host`에 넣고 2.4 GHz SSID를 별도 입력하도록 안내 |

## 2026-11-15 업로드 후 등록 확인

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| 펌웨어 host 설정 확인 | Codex | `timeout 5 rg -n '^#define SERVER_HOST|^#define SERVER_PORT' firmware/beacon_node/config.h` | 0 | `SERVER_HOST=192.168.219.123`, `SERVER_PORT=8080` |
| 새 Wi-Fi 빌드 로그 확인 | Codex | `timeout 5 cat results/wifi_rebuild.log` | 0 | 플래시 1,071,665 bytes(81%), RAM 61,856 bytes(18%) 표시. CLI 종료 코드는 로그 파일에 별도 기록되지 않음 |
| 업로드 및 모니터 | 사람 | `bash /home/nano/beacon/firmware/flash.sh` | upload 0; monitor 124 | 사용자 제공 로그에서 이미지 해시 확인 및 업로드 성공. 모니터 시간초과, `IP not found`; 저장된 `serial_boot.log`는 0 bytes여서 시리얼 부팅 정보 미확인 |
| 관리 API 등록 조회 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes` | 1 | `127.0.0.1:8081` connection refused |
| 서버 프로세스 조회 | Codex | `timeout 5 pgrep -af '[b]eacon_server.py'` | 1 | 출력 없음; 조회 시점에 서버 프로세스 없음 |
| 서버 설정 파일 존재 확인 | Codex | `timeout 5 bash -c 'if test -f server/config.json; then echo CONFIG_PRESENT; else echo CONFIG_MISSING; fi'` | 0 | `CONFIG_PRESENT` |
| 이미지 요청 명령 3 등록 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py image tc-004f8c --fs VGA --q 12 --warm 500` | 0 | `cmd_id=3`, `state=queued` |
| 이미지 명령 3 전달 여부 확인 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py cmd 3` | 0 | `dispatched_at=null`, `attempts=0`; 명령은 아직 노드에 전달되지 않음 |
| 이미지 요청 전 노드 상태 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py nodes` | 0 | 노드 `ATTACHED`이나 `online=offline`; 마지막 체크인과 IP `192.168.25.45`는 새 네트워크 확인 전의 오래된 값 |

판정: 업로드는 성공했으나 서버 프로세스가 실행 중이지 않아 현재 노드 등록은 확인되지 않았습니다. 설정된 Jetson 주소는 새 IPv4와 일치합니다. 이후 관리 API가 응답했지만 노드 레코드는 여전히 offline/stale이었습니다. 이미지 명령 3은 등록됐으나 `attempts=0`이라 아직 수신되지 않았고, 약 15분 내 만료됩니다. `flash.sh`의 빈/오래된 모니터 로그는 IP 할당 여부를 판정하지 못하므로, 보드를 켜고 직접 모니터를 연 뒤 RESET으로 체크인을 유도해야 합니다. 새 SSID가 2.4 GHz를 제공하는지는 사람 확인이 필요합니다.

## 2026-11-15 Wi-Fi 연결 진단

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| ESP32 Wi-Fi/RTC 부팅 로그 | 사람 | `timeout -s INT -k 3 70 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off` | 미제공 | `WIFI failed status=1 wifi_ms=15005`; 이후 `RTC_TIMER armed=1 requested_ticks=60 read_ticks=59 first_tick_short=1`, `POWER_OFF next_s=3600 result=wifi_fail` |
| 상태 코드 대조 | Codex | `timeout 5 sed -n '38,54p' /mnt/nvme/arduino/data/packages/esp32/hardware/esp32/3.3.12/libraries/WiFi/src/WiFiType.h` | 0 | 코어 3.3.12에서 값 1은 `WL_NO_SSID_AVAIL`; STA.cpp는 `WIFI_REASON_NO_AP_FOUND` 때 이 상태를 설정 |

판정: 실패 지점은 서버 체크인이 아니라 Wi-Fi 연결 단계입니다. 보드가 설정된 SSID를 찾지 못했습니다. Timer Camera는 2.4 GHz만 지원하므로 현재 SSID가 5 GHz 전용이면 2.4 GHz SSID를 설정하고 재컴파일·업로드해야 합니다. RTC 타이머는 60초 설정으로 arm됐고, 최초 1틱 짧은 readback은 정상 허용 범위입니다. 실패 후 다음 시도 간격은 `next_s=3600`초입니다. Wi-Fi 비밀번호/SSID는 읽거나 기록하지 않았습니다.

같은 진단 로그를 반복하기 위한 임시 변경: Wi-Fi 연결 실패 경로만 기존 지수 백오프 대신 5초 후 재시도하도록 수정했습니다. 정상 체크인 간격과 HTTP 실패 백오프는 유지했습니다. N3 컴파일 종료 코드 0, 플래시 1,071,637 bytes(81%), RAM 61,856 bytes(18%). 이 테스트 빌드는 아직 업로드하지 않았습니다. 테스트 후 운영 백오프를 복구해야 합니다.

## 2026-11-15 이미지 요청 재시험

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| 새 네트워크 체크인 | 사람 | `timeout -s INT -k 3 70 /home/nano/bin/arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200 -c dtr=off -c rts=off` | 미제공 | IP `192.168.219.124`, `CHECKIN ok next_s=56 commands=0`, `rtc_timer=1` 확인 |
| 이미지 명령 3 상태 | 사람 | `python3 /home/nano/beacon/tools/beaconctl.py cmd 3` | 미제공 | 명령 3은 `expired`, `attempts=0`; 수신되지 않음 |
| 이미지 명령 4 등록 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py image tc-004f8c --fs VGA --q 12 --warm 500` | 0 | `cmd_id=4`, `state=queued` |
| 이미지 명령 4 결과 | Codex | `timeout 10 python3 /home/nano/beacon/tools/beaconctl.py cmd 4` | 1 | `dispatched_at` 설정, `attempts=1`, `failed(camera_init 0x103)`; JPEG 결과 없음 |

## 2026-11-15 Camera SCCB/I2C 충돌 진단과 수정

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| 카메라 초기화 로그 | 사람 | 이미지 명령 실행 중 시리얼 모니터 | 미제공 | `I2C bus id(1) has already been acquired`, `failed to install SCCB I2C master bus on port 1: ESP_ERR_INVALID_STATE`, `Camera probe failed ... 0x103` |
| 소스 대조 | Codex | `timeout 10 rg -n "Wire1|esp_camera|pin_sccb" firmware/beacon_node` | 0 | `rtc_bm8563.cpp`에서 RTC가 `Wire1.begin(12,14,100000)`로 controller 1을 시작하고 사이클 내내 유지. 코어 카메라 SCCB도 controller 1 사용 |
| RTC 버스 사용 시간 수정 | Codex | 소스 수정 | — | 부팅 시 RTC 플래그를 읽은 뒤 `Wire1.end()`로 버스 해제. 카메라 명령은 해제 실패 시 중단. 전원 차단 전 RTC 타이머 설정에서 `Wire1` 재초기화 |
| N3 수정 펌웨어 컴파일 | Codex | `/home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node` | 0 | `results/compile_i2c_bus_fix.log`; flash 1,071,953 bytes (81%), RAM 61,856 bytes (18%) |

판정: `0x103`은 카메라 센서나 핀맵 문제로 확인된 것이 아니라 RTC와 SCCB가 같은 ESP32 I2C controller 1을 동시에 점유한 충돌이다. 펌웨어 버스 수명을 분리해 컴파일까지 성공했다. 새 빌드는 아직 보드에 업로드되지 않았으므로 카메라 초기화 및 JPEG 수신은 **사람 실행 대기**다. 사람은 업로드 뒤 `RTC I2C released_for_camera=1`, `CHECKIN ... commands=1`, 카메라 init 성공 로그, `beaconctl cmd <id>`의 이미지 결과를 확인해야 한다. 추가 핀/카메라 설정 변경은 하지 않았다.

## 2026-11-17 USB 로컬 진단 모드

사용자가 서버 의존 없이 USB 시리얼로 온습도 센서 연결과 보드 데이터를 확인하도록 진단 메뉴를 추가했다. 일반 펌웨어 기본값은 `USB_DIAGNOSTIC_MODE=0`; 진단 산출물만 `-DUSB_DIAGNOSTIC_MODE=1`로 컴파일했다.

| 단계 | 담당 | 명령 | 종료 코드 | 결과 |
|---|---|---|---:|---|
| USB 진단 펌웨어 컴파일(두 배선 방향 추가) | Codex | `/home/nano/bin/arduino-cli compile --fqbn esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000 --build-property 'compiler.cpp.extra_flags=-DUSB_DIAGNOSTIC_MODE=1' --output-dir /home/nano/beacon/firmware/build /home/nano/beacon/firmware/beacon_node` | 0 | `results/usb_diag_compile.log`; flash 1,017,725 bytes (77%), RAM 59,240 bytes (18%) |
| 진단 모드 문자열 포함 확인 | Codex | `timeout 10 strings firmware/build/beacon_node.ino.bin` | 0 | 산출물에 `USB_DIAG_READY`, `I2C_SCAN`, `SHT30`, `CAMERA_DIAG`, `WIFI_DIAG` 존재 |
| 보드 업로드 및 실제 진단 | 사람 | `bash /home/nano/beacon/firmware/flash.sh`, 이후 `arduino-cli monitor` | 사람 실행 대기 | Codex는 `/dev/ttyUSB0`에 접근하거나 업로드하지 않음 |

USB 메뉴 명령: `help`, `status`, `i2c`, `sensor`, `wifi`, `camera`, `all`, `sleep`. `sensor`는 Grove G4/G13 및 G13/G4 두 순서에서 SHT30 0x44/0x45와 DHT20 0x38을 시험하고 line level, SHT30 raw 6바이트, DHT20 raw 7바이트, CRC, 변환값, JSON을 시리얼로 표시한다. `all`은 RTC 레지스터/NVS/battery ADC/heap/PSRAM/Wi-Fi 상태와 I2C, 센서, 카메라를 검사한다. 진단 모드는 서버를 호출하지 않고 최대 15분 뒤 deep sleep한다. 실제 센서 측정 결과는 아직 나오지 않았다.

## 2026-11-17 USB 실기 진단 결과

| 대상 | 로그 근거 | 판정 |
|---|---|---|
| RTC | `bus=rtc ... addr=0x51`, `RTC available=1` | BM8563은 G12/G14 버스에서 응답 |
| Grove 센서 버스 | `I2C_SCAN_DONE bus=grove devices=0`; SHT30 `tx_result=4`, DHT20 `probe_result=5` | G4/G13에서 장치가 응답하지 않음. 온습도 측정값 없음 |
| 카메라 | `CAMERA_DIAG result=ok ... 640x480 ... jpeg_soi=1 jpeg_eoi=1` | OV3660 초기화와 캡처 성공. 카메라 SCCB의 사전 scan 결과 0은 이후 카메라 캡처 성공과 모순되지 않음 |
| Wi-Fi | `connected=1 status=3`, IP `192.168.219.124`, RSSI -41, channel 8 | AP 접속 정상. 진단 모드는 Beacon 서버 요청을 하지 않음 |
| 전압 | ADC 평균 2841mV, `VBAT_SCALE=2.00`, `calibrated=0` | 보정 전 값이므로 배터리 전압/잔량 판정에 사용하지 않음 |

결론: 펌웨어의 SHT30 읽기 로직까지 도달했지만 Grove 버스에서 ACK를 받지 못해 `sensor_absent`를 반환했다. 센서가 물리적으로 연결되지 않았다고 단정할 수는 없으며, 케이블 방향/핀 매핑, 전원·GND, SDA/SCL 연결 또는 모듈 주소/호환성을 확인해야 한다. 현재 명세 기준 센서 버스는 G4(SDA)/G13(SCL), SHT30 주소는 0x44 또는 0x45다. 사람의 배선 확인 후 동일한 `sensor` 또는 `all` USB 진단 명령으로 재측정한다.

두 데이터 선 방향을 바꿔 다시 실행한 로그에서도 두 SHT30 주소는 ACK를 주지 않았고 Grove scan은 0개였다. DHT20 probe 코드는 첫 시험 `5`(timeout), 다음 시험 `2`(address NACK)로 달랐다. 코어 3.3.12 `Wire.cpp`의 반환 규약에서 2는 주소 NACK, 4는 기타 오류, 5는 timeout이다. SHT30 측정 명령을 보내는 경로의 `tx_result=4`는 구체 원인을 반환하지 않는다. 이에 진단 빌드에 양쪽 SDA/SCL 배치를 각각 scan/read하고 idle line level을 출력하도록 추가했으며, 재컴파일은 exit 0이다. 새 산출물 플래시와 양방향 비교 결과는 사람 실행 대기다.

사람 실행의 최신 진단 빌드 결과: G4 SDA/G13 SCL과 G13 SDA/G4 SCL 양쪽 모두 I2C scan 장치 0개, SHT30 0x44/0x45 `tx_result=4`, DHT20 0x38 `probe_result=2`; 센서 raw byte/온습도값은 없음. 두 핀 방향을 바꾸는 것만으로 해결되지 않았다. `I2C_LINES level=1`은 진단 코드가 `INPUT_PULLUP`을 설정한 뒤 읽은 디지털 상태라 외부 pull-up, VCC/GND 연결, 센서 전원을 검증한 값이 아니다. 카메라 캡처와 Wi-Fi 연결은 이 시험에서도 성공했다.

판정: 새 Wi-Fi/서버 통신과 이미지 명령 전달은 성공했습니다. 촬영은 카메라 초기화 `0x103`에서 실패해 이미지 파일은 수신되지 않았습니다. 추가 명령은 등록하지 않았습니다.

