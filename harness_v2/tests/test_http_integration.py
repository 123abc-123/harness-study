"""Real loopback HTTP transport with scripted replies, never an external model service."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from internal_harness.agent import Agent
from internal_harness.model import InternalHTTPModel, ModelConfig
from internal_harness.runtime import Runtime


class HTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.response_mode = "chat_tools"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(request)
                if owner.response_mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://should-never-be-contacted.invalid/")
                    self.end_headers()
                    return
                first = len(owner.requests) == 1
                action = {"action": "tool", "name": "write_file", "arguments": {
                    "path": "outputs/from-http.txt", "content": "actual HTTP -> tool -> file"}}
                if owner.response_mode == "json_actions":
                    content = json.dumps(action if first else {"action": "final", "answer": "done"})
                    message = {"role": "assistant", "content": content}
                elif first:
                    message = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": "http-1", "type": "function", "function": {
                            "name": "write_file", "arguments": json.dumps(action["arguments"])}}]}
                else:
                    message = {"role": "assistant", "content": "done"}
                payload = json.dumps({"choices": [{"message": message}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except OSError as error:
            self.skipTest(f"Environment disallows loopback listener: {error}")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        base = Path(__file__).resolve().parent.parent / ".test-workspace"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        assert Path(self.temp.name).resolve().is_relative_to(Path(__file__).resolve().parent.parent / ".test-workspace")
        self.temp.cleanup()

    def run_mode(self, mode):
        self.response_mode = mode
        config = ModelConfig(endpoint=self.url + "/v1/chat/completions", allowed_origins=(self.url,),
                             model="test-only", protocol=mode, timeout_seconds=5)
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            result = Agent(Runtime(self.temp.name), InternalHTTPModel(config)).run("Write the file")
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual((Path(self.temp.name) / "outputs/from-http.txt").read_text(), "actual HTTP -> tool -> file")

    def test_native_tools_over_actual_http(self):
        self.run_mode("chat_tools")
        self.assertIn("tools", self.requests[0])

    def test_json_actions_over_actual_http(self):
        self.run_mode("json_actions")
        self.assertNotIn("tools", self.requests[0])

    def test_actual_redirect_is_rejected(self):
        self.response_mode = "redirect"
        client = InternalHTTPModel(ModelConfig(endpoint=self.url + "/redirect", allowed_origins=(self.url,), model="test"))
        with self.assertRaises(RuntimeError):
            client.complete([], [])
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
