#!/usr/bin/env bash
set -u
ROOT=/home/nano/beacon
cd "$ROOT" || exit 1
timeout 5 mkdir -p "$ROOT/results" || exit 1
LOG="$ROOT/results/n2.log"
timeout 5 touch "$LOG" || { echo 'N2 exit=1 reason=log_init'; exit 1; }
exec 3>&1 4>&2
exec >"$LOG" 2>&1

data_dir_fail() {
  local rc="$1"
  local message="N2 exit=$rc reason=data_dir"
  printf '%s\n' "$message"
  printf '%s\n' "$message" >&3
  exit "$rc"
}

timeout 5 bash -c 'test -d "$1" && test -w "$1"' _ /mnt/nvme/beacon
data_base_rc=$?
if [[ "$data_base_rc" -ne 0 ]]; then data_dir_fail "$data_base_rc"; fi

stamp=$(timeout 5 date +%Y%m%d_%H%M%S) || { rc=$?; printf 'N2 exit=%s reason=timestamp\n' "$rc"; printf 'N2 exit=%s reason=timestamp\n' "$rc" >&3; exit "$rc"; }
DATA_DIR="/mnt/nvme/beacon/sim_$stamp"
timeout 10 mkdir -p "$DATA_DIR"
data_dir_rc=$?
if [[ "$data_dir_rc" -ne 0 ]]; then data_dir_fail "$data_dir_rc"; fi
timeout 10 python3 -c '
import json, pathlib, socket, sys
root = pathlib.Path(sys.argv[1])
cfg = json.loads(pathlib.Path("server/config.example.json").read_text(encoding="utf-8"))
def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port
cfg["node_port"] = free_port()
cfg["admin_port"] = free_port()
cfg["test_mode"] = True
cfg["test_min_next_s"] = 5
cfg["test_discovered_next_s"] = 5
cfg["test_detached_next_s"] = 5
cfg["data_dir"] = str(root)
cfg["db_path"] = str(root / "beacon.db")
cfg["images_dir"] = str(root / "images")
(root / "config.json").write_text(json.dumps(cfg, indent=2) + chr(10), encoding="utf-8")
node_port, admin_port = cfg["node_port"], cfg["admin_port"]
(root / "ports.txt").write_text(str(node_port) + " " + str(admin_port) + chr(10), encoding="ascii")
' "$DATA_DIR"
config_rc=$?
if [[ "$config_rc" -ne 0 ]]; then
  printf 'N2 config generation failed exit=%s\n' "$config_rc"
  printf 'N2 exit=%s\nAC2=NOT_RUN AC3=NOT_RUN AC4=NOT_RUN\n' "$config_rc"
  exit "$config_rc"
fi
read -r NODE_PORT ADMIN_PORT < "$DATA_DIR/ports.txt"
NODE_URL="http://127.0.0.1:$NODE_PORT"
ADMIN_URL="http://127.0.0.1:$ADMIN_PORT"
CONFIG="$DATA_DIR/config.json"
SERVER_PID=
SERVER_WAIT_RC=not-stopped
SIM_RC=1
VERIFY_RC=1
REPORT_CURRENT=0

stop_server() {
  if [[ -n "$SERVER_PID" ]]; then
    kill -INT "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID"
    SERVER_WAIT_RC=$?
    printf 'server wait exit=%s\n' "$SERVER_WAIT_RC"
    SERVER_PID=
  fi
}
trap stop_server EXIT
trap 'stop_server; exit 130' INT
trap 'stop_server; exit 143' TERM
trap 'stop_server; exit 148' TSTP

timeout --foreground -s INT -k 3 360 python3 server/beacon_server.py --config "$CONFIG" >"$ROOT/results/n2_server.log" 2>&1 &
SERVER_PID=$!
SERVER_PID_CHECK=$SERVER_PID

READY=0
for ((i=0; i<30; i++)); do
  code=$(timeout 4 curl -sS -m 2 -o "$DATA_DIR/ready.json" -w '%{http_code}' "$ADMIN_URL/admin/nodes" 2>>"$ROOT/results/n2_server.log")
  curl_rc=$?
  if [[ "$curl_rc" -eq 0 && "$code" == 200 ]]; then READY=1; break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  timeout 2 sleep 1
done
if [[ "$READY" -ne 1 ]]; then
  echo 'N2 server readiness failed; see results/n2_server.log.'
  timeout 5 tail -n 30 "$ROOT/results/n2_server.log"
  SIM_RC=1
else
  echo "N2 running 20 nodes for 300 s; data=$DATA_DIR"
  timeout 330 python3 sim/sim_nodes.py --n 20 --server "$NODE_URL" --admin-url "$ADMIN_URL" --duration 300 --seed 1 --test-mode --exercise-admin --db "$DATA_DIR/beacon.db" --report "$DATA_DIR/sim_raw.json" >"$ROOT/results/n2_simulator.log" 2>&1
  SIM_RC=$?
  timeout 5 tail -n 30 "$ROOT/results/n2_simulator.log"
fi

stop_server
trap - EXIT INT TERM TSTP
if kill -0 "$SERVER_PID_CHECK" 2>/dev/null; then
  echo 'server process is still running after shutdown'
  SIM_RC=1
fi
timeout 4 curl -sS -m 2 "$ADMIN_URL/admin/nodes" >/dev/null 2>&1
post_stop_rc=$?
if [[ "$post_stop_rc" -eq 0 ]]; then
  echo 'management API still responds after server shutdown'
  SIM_RC=1
fi
if [[ -f "$DATA_DIR/sim_raw.json" ]]; then
  timeout 30 python3 sim/verify_sim.py --db "$DATA_DIR/beacon.db" --input "$DATA_DIR/sim_raw.json" --output "$ROOT/results/sim_report.json"
  VERIFY_RC=$?
  REPORT_CURRENT=1
else
  echo 'sim_raw.json missing; AC2-AC4 cannot be evaluated'
fi

AC2=NOT_RUN
AC3=NOT_RUN
AC4=NOT_RUN
if [[ "$REPORT_CURRENT" -eq 1 && -f "$ROOT/results/sim_report.json" ]]; then
  summary=$(timeout 5 python3 -c 'import json,sys; a=json.load(open(sys.argv[1], encoding="utf-8"))["acceptance"]; print(" ".join(k+"="+("PASS" if v else "FAIL") for k,v in a.items()))' "$ROOT/results/sim_report.json")
  summary_rc=$?
  if [[ "$summary_rc" -eq 0 ]]; then
    echo "$summary"
    AC2=$(echo "$summary" | timeout 5 awk '{for(i=1;i<=NF;i++) if($i~/^AC2_/) print $i}')
    AC3=$(echo "$summary" | timeout 5 awk '{for(i=1;i<=NF;i++) if($i~/^AC3_/) print $i}')
    AC4=$(echo "$summary" | timeout 5 awk '{for(i=1;i<=NF;i++) if($i~/^AC4_/) print $i}')
  else
    VERIFY_RC=$summary_rc
  fi
fi
N2_RC=0
if [[ "$SIM_RC" -ne 0 || "$VERIFY_RC" -ne 0 || "$AC2" != *PASS* || "$AC3" != *PASS* || "$AC4" != *PASS* ]]; then N2_RC=1; fi
if [[ "$SERVER_WAIT_RC" == not-stopped ]]; then N2_RC=1; fi
printf 'server shutdown confirmed (wait exit=%s, post-stop curl exit=%s)\n' "$SERVER_WAIT_RC" "$post_stop_rc"
printf 'N2 exit=%s\nAC2=%s AC3=%s AC4=%s\n' "$N2_RC" "$AC2" "$AC3" "$AC4"
exit "$N2_RC"

