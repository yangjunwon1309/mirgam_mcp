import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server.beacon_server import BeaconApplication, jpeg_dimensions, make_server
from server.store import Store


def jpeg_with_sof(width=640, height=480, marker=0xC0):
    payload = bytes((8, height >> 8, height & 255, width >> 8, width & 255, 3,
                     1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1))
    return b"\xff\xd8\xff" + bytes((marker,)) + (len(payload) + 2).to_bytes(2, "big") + payload + b"\xff\xd9"


def checkin_body(seq=1):
    return {
        "v": 1, "fw": "beacon-0.1.0", "boot": "cold", "seq": seq,
        "vbat_mv": 3980, "rssi": -55, "ch": 6,
        "t": {"wifi_ms": 640, "fast": 1, "prev_awake_ms": 2100, "prev_result": "ok"},
    }


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beacon-http-test-")
        root = Path(self.temp.name)
        config = {
            "node_port": 0, "admin_port": 0, "data_dir": str(root),
            "db_path": str(root / "beacon.db"), "images_dir": str(root / "images"),
            "default_interval_s": 60, "vbat_low_mv": 3450, "vbat_critical_mv": 3300,
            "test_mode": True, "test_min_next_s": 5,
        }
        self.app = BeaconApplication(config, Store(config["db_path"]))
        self.node_server = make_server("127.0.0.1", 0, self.app, False)
        self.admin_server = make_server("127.0.0.1", 0, self.app, True)
        self.node_thread = threading.Thread(target=self.node_server.serve_forever, daemon=True)
        self.admin_thread = threading.Thread(target=self.admin_server.serve_forever, daemon=True)
        self.node_thread.start()
        self.admin_thread.start()
        self.node_base = f"http://127.0.0.1:{self.node_server.server_port}"
        self.admin_base = f"http://127.0.0.1:{self.admin_server.server_port}"

    def tearDown(self):
        self.node_server.shutdown()
        self.admin_server.shutdown()
        self.node_server.server_close()
        self.admin_server.server_close()
        self.node_thread.join(timeout=3)
        self.admin_thread.join(timeout=3)
        self.app.close()
        self.temp.cleanup()

    def request(self, base, path, method="GET", body=None, headers=None):
        data = None
        sent_headers = dict(headers or {})
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            sent_headers.setdefault("Content-Type", "application/json")
        request = Request(base + path, data=data, headers=sent_headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()

    def node_headers(self, token=None):
        headers = {"X-Node-Id": "tc-a1b2c3"}
        if token is not None:
            headers["X-Token"] = token
        return headers

    def checkin(self, token=None, seq=1):
        return self.request(
            self.node_base, "/api/v1/checkin", "POST", checkin_body(seq),
            self.node_headers(token),
        )

    def attach(self):
        self.app.store.ensure_node("tc-a1b2c3")
        return self.request(
            self.admin_base, "/admin/nodes/tc-a1b2c3/attach", "POST",
            {"interval_s": 60},
        )

    def test_checkin_attach_token_command_result_and_duplicate(self):
        status, body = self.checkin()
        self.assertEqual(status, 200)
        self.assertIn(b"next=", body)
        self.assertTrue(body.endswith(b"end\n"))

        self.assertEqual(self.attach()[0], 200)
        queued_status, queued_body = self.request(
            self.admin_base, "/admin/nodes/tc-a1b2c3/commands", "POST",
            {"type": "sensor", "params": {}},
        )
        self.assertEqual(queued_status, 202)
        cmd_id = json.loads(queued_body)["cmd_id"]

        status, body = self.checkin(seq=2)
        self.assertEqual(status, 200)
        lines = body.decode().splitlines()
        token = next(line[4:] for line in lines if line.startswith("tok="))
        self.assertEqual(len(token), 32)
        self.assertIn(f"cmd={cmd_id} sensor", body.decode())

        self.assertEqual(
            self.request(self.node_base, "/api/v1/poll?wait=0", headers=self.node_headers("f" * 32))[0],
            401,
        )
        result_headers = self.node_headers(token)
        result_path = f"/api/v1/result?cmd={cmd_id}"
        result = {"ok": 1, "sensors": [{"type": "sht30", "addr": 68, "t_c": 21.43, "rh": 63.2}]}
        self.assertEqual(self.request(self.node_base, result_path, "POST", result, result_headers)[0], 200)
        self.assertEqual(self.request(self.node_base, result_path, "POST", result, result_headers), (200, b"dup"))
        command = self.app.store.get_command(cmd_id)
        self.assertEqual(command["state"], "done")
        self.assertEqual(self.app.store.db.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)

    def test_long_poll_wakes_on_command_and_times_out(self):
        self.assertEqual(self.checkin()[0], 200)
        self.assertEqual(self.attach()[0], 200)
        self.assertEqual(
            self.request(self.admin_base, "/admin/nodes/tc-a1b2c3/session", "POST", {"hold_s": 10})[0],
            200,
        )
        status, body = self.checkin(seq=2)
        self.assertEqual(status, 200)
        token = next(line[4:] for line in body.decode().splitlines() if line.startswith("tok="))
        self.assertIn("hold=10", body.decode())

        result = {}

        def poll():
            result["response"] = self.request(
                self.node_base, "/api/v1/poll?wait=5", headers=self.node_headers(token)
            )

        thread = threading.Thread(target=poll)
        thread.start()
        time.sleep(0.1)
        queued_status, queued_body = self.request(
            self.admin_base, "/admin/nodes/tc-a1b2c3/commands", "POST",
            {"type": "config", "params": {"fast": 1}},
        )
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(queued_status, 202)
        self.assertIn(f"cmd={json.loads(queued_body)['cmd_id']} config fast=1", result["response"][1].decode())

        started = time.monotonic()
        status, body = self.request(
            self.node_base, "/api/v1/poll?wait=1", headers=self.node_headers(token)
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.endswith(b"end\n"))
        self.assertLess(time.monotonic() - started, 2.5)

    def test_truncated_request_returns_400(self):
        sock = socket.create_connection(("127.0.0.1", self.node_server.server_port), timeout=3)
        sock.settimeout(3)
        sock.sendall(
            b"POST /api/v1/checkin HTTP/1.1\r\nHost: localhost\r\n"
            b"X-Node-Id: tc-abcdef\r\nContent-Type: application/json\r\n"
            b"Content-Length: 50\r\nConnection: close\r\n\r\n{}"
        )
        sock.shutdown(socket.SHUT_WR)
        response = sock.recv(1024)
        sock.close()
        self.assertIn(b"400", response.split(b"\r\n", 1)[0])

    def test_jpeg_sof0_sof2_dimensions_and_bad_markers(self):
        self.assertEqual(jpeg_dimensions(jpeg_with_sof()), (640, 480))
        self.assertEqual(jpeg_dimensions(jpeg_with_sof(320, 240, 0xC2)), (320, 240))
        self.assertIsNone(jpeg_dimensions(b"not a jpeg"))

    def test_detached_node_cannot_queue_command(self):
        self.app.store.ensure_node("tc-a1b2c3")
        self.assertEqual(self.request(self.admin_base, "/admin/nodes/tc-a1b2c3/detach", "POST", {})[0], 200)
        status, body = self.request(
            self.admin_base, "/admin/nodes/tc-a1b2c3/commands", "POST",
            {"type": "sensor", "params": {}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.app.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
