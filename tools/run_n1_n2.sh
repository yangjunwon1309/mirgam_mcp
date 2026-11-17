#!/usr/bin/env bash
set -u

ROOT=/home/nano/beacon
cd "$ROOT" || exit 1
timeout 5 mkdir -p "$ROOT/results" || exit 1

printf 'N1: unit tests are delegated to this host-side script because N0 loopback bind was denied in Codex.\n'
timeout 180 python3 -m unittest discover -s server/tests -v \
  > "$ROOT/results/n1_unittest.log" 2>&1
n1_rc=$?
printf 'N1 unittest exit=%s\n' "$n1_rc"
if [[ "$n1_rc" -ne 0 ]]; then
  timeout 5 tail -n 30 "$ROOT/results/n1_unittest.log"
  exit "$n1_rc"
fi

temp_dir=$(timeout 5 mktemp -d /tmp/beacon-n1-n2.XXXXXX)
if [[ -z "$temp_dir" ]]; then
  printf 'Could not create a temporary simulation directory.\n' >&2
  exit 1
fi

timeout 10 python3 -c '
import json, pathlib, socket, sys
root = pathlib.Path(sys.argv[1])
config = json.loads(pathlib.Path("server/config.example.json").read_text())
def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port
config["node_port"] = free_port()
config["admin_port"] = free_port()
config["test_mode"] = True
config["test_min_next_s"] = 5
config["test_discovered_next_s"] = 5
config["test_detached_next_s"] = 5
config["data_dir"] = str(root / "data")
config["db_path"] = str(root / "data" / "beacon.db")
config["images_dir"] = str(root / "data" / "images")
(root / "config.json").write_text(json.dumps(config, indent=2) + "\n")
node_port = config["node_port"]
admin_port = config["admin_port"]
(root / "ports.txt").write_text(f"{node_port} {admin_port}\n")
' "$temp_dir"
config_rc=$?
if [[ "$config_rc" -ne 0 ]]; then
  printf 'Test configuration generation failed (exit=%s).\n' "$config_rc" >&2
  exit "$config_rc"
fi
read -r node_port admin_port < "$temp_dir/ports.txt"
node_url="http://127.0.0.1:$node_port"
admin_url="http://127.0.0.1:$admin_port"

server_pid=
server_exit=not-stopped
cleanup_server() {
  if [[ -n "$server_pid" ]]; then
    kill -TERM "$server_pid" 2>> "$ROOT/results/harness.log" || true
    wait "$server_pid"
    server_exit=$?
    printf 'test server wait exit=%s\n' "$server_exit" >> "$ROOT/results/harness.log"
    server_pid=
  fi
}
trap cleanup_server EXIT

timeout -s INT -k 3 360 python3 server/beacon_server.py --config "$temp_dir/config.json" \
  > "$ROOT/results/sim_server.log" 2>&1 &
server_pid=$!

ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
  code=$(timeout 4 curl -sS -m 2 -o "$temp_dir/readiness.json" -w '%{http_code}' "$admin_url/admin/nodes" 2>> "$ROOT/results/harness.log")
  curl_rc=$?
  if [[ "$curl_rc" -eq 0 && "$code" == "200" ]]; then
    ready=1
    break
  fi
  if ! kill -0 "$server_pid" 2>> "$ROOT/results/harness.log"; then
    break
  fi
  timeout 2 sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  printf 'Test server failed readiness check. See results/sim_server.log.\n' >&2
  timeout 5 tail -n 30 "$ROOT/results/sim_server.log"
  exit 1
fi

printf 'N2: starting 20-node, 300-second simulation; temporary data: %s\n' "$temp_dir/data"
timeout 330 python3 sim/sim_nodes.py --n 20 --server "$node_url" --admin-url "$admin_url" \
  --duration 300 --seed 1 --test-mode --exercise-admin \
  --db "$temp_dir/data/beacon.db" --report "$ROOT/results/sim_raw.json" \
  > "$ROOT/results/sim_nodes.log" 2>&1
sim_rc=$?
printf 'N2 simulator exit=%s\n' "$sim_rc"
timeout 5 tail -n 30 "$ROOT/results/sim_nodes.log"
if [[ -f "$ROOT/results/sim_raw.json" ]]; then
  timeout 30 python3 sim/verify_sim.py --db "$temp_dir/data/beacon.db" \
    --input "$ROOT/results/sim_raw.json" --output "$ROOT/results/sim_report.json"
  verify_rc=$?
  printf 'N2 verification exit=%s\n' "$verify_rc"
  if [[ "$verify_rc" -ne 0 ]]; then sim_rc=$verify_rc; fi
fi

server_pid_to_check=$server_pid
cleanup_server
trap - EXIT
if kill -0 "$server_pid_to_check" 2>> "$ROOT/results/harness.log"; then
  printf 'Server process still appears active after wait.\n' >&2
  exit 1
fi
printf 'Server stopped; logs and sim_report.json are under results/.\n'
exit "$sim_rc"
