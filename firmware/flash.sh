#!/usr/bin/env bash
set -u
ROOT=/home/nano/beacon
SKETCH="$ROOT/firmware/beacon_node"
BUILD="$ROOT/firmware/build"
RESULTS="$ROOT/results"
CLI=/home/nano/bin/arduino-cli
PORT=/dev/ttyUSB0
SPEED=${UPLOAD_SPEED:-500000}

case "$SPEED" in
  1500000|750000|500000|250000|115200) ;;
  *) echo "UPLOAD_SPEED must be one of 1500000|750000|500000|250000|115200"; exit 2 ;;
esac
timeout 5 mkdir -p "$RESULTS" || exit 1
if [[ ! -e "$PORT" ]]; then
  echo "$PORT not found; run this script from the host shell with the Timer Camera connected."
  exit 1
fi
FQBN="esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=$SPEED"
set +e
timeout 300 "$CLI" upload -p "$PORT" --fqbn "$FQBN" --input-dir "$BUILD" "$SKETCH" 2>&1 | timeout 310 tee "$RESULTS/upload.log"
pipe_status=("${PIPESTATUS[@]}")
upload_rc=${pipe_status[0]}
printf 'upload exit=%s\n' "$upload_rc"
if [[ "$upload_rc" -ne 0 ]]; then exit "$upload_rc"; fi

echo "Wait for 'Connecting to $PORT' in the monitor, then press the board RESET button once."
monitor_cmd="$CLI monitor -p $PORT -c baudrate=115200 -c dtr=off -c rts=off"
timeout -s INT -k 3 25 /usr/bin/script --quiet --return --flush --command "$monitor_cmd" "$RESULTS/serial_boot.log"
monitor_rc=$?
printf 'monitor exit=%s\n' "$monitor_rc"
if [[ "$monitor_rc" -eq 137 ]]; then
  echo 'monitor was force-stopped by timeout after the 3-second interrupt grace period; captured log is retained.'
fi

ip=$(timeout 5 grep -a '^IP=' "$RESULTS/serial_boot.log" | timeout 5 awk '$1 ~ /^IP=/ && $1 != "IP=0.0.0.0" {sub(/^IP=/,"",$1); value=$1} END {if (value != "") print value}')
grep_rc=$?
if [[ "$grep_rc" -eq 0 && -n "$ip" ]]; then
  timeout 5 bash -c 'printf "%s\n" "$1" > "$2"' _ "$ip" "$RESULTS/ip.txt"
  echo "IP=$ip"
else
  echo 'IP not found'
fi
exit 0

