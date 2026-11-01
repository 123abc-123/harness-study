import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from internal_harness.agent import Agent
from internal_harness.model import InternalHTTPModel, ModelConfig, ModelProtocolError, NoRedirect
from internal_harness.runtime import Runtime


def config(**kwargs):
    return ModelConfig(**{"endpoint": "http://127.0.0.1:8000/v1/chat/completions",
                          "allowed_origins": ("http://127.0.0.1:8000",), "model": "test-model", **kwargs})


def envelope(content=None, calls=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"choices": [{"message": message}]}


class ModelTests(unittest.TestCase):
    def test_no_default_endpoint_or_allowlist(self):
        with self.assertRaises(TypeError):
            ModelConfig(model="test")
        with self.assertRaises(ValueError):
            config(allowed_origins=())

    def test_exact_origin_including_port(self):
        for endpoint in ("http://127.0.0.1:8001/v1/chat", "https://unapproved.invalid/chat",
                         "http://user:secret@127.0.0.1:8000/chat", "http://127.0.0.1:8000/chat?token=abc"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                config(endpoint=endpoint)

    def test_internal_http_requires_explicit_opt_in(self):
        fields = {"endpoint": "http://inference.internal/chat", "allowed_origins": ("http://inference.internal",)}
        with self.assertRaises(ValueError):
            config(**fields)
        self.assertTrue(config(**fields, allow_http=True).allow_http)

    def test_config_types_and_protocol(self):
        for fields in ({"timeout_seconds": True}, {"max_response_bytes": 1},
                       {"protocol": "arbitrary"}, {"allowed_origins": ["http://127.0.0.1:8000/path"]}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                config(**fields)

    def test_credentials_are_explicit(self):
        with patch.dict(os.environ, {"INTERNAL_TOKEN": ""}), self.assertRaises(ValueError):
            InternalHTTPModel(config(auth_env="INTERNAL_TOKEN"))
        with patch.dict(os.environ, {"UNRELATED_PROVIDER_KEY": "do-not-use"}):
            self.assertEqual(InternalHTTPModel(config()).token, "")

    def test_redirect_is_never_followed(self):
        with self.assertRaises(RuntimeError):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.invalid/")

    def test_native_tool_protocol(self):
        client = InternalHTTPModel(config())
        calls = [{"id": "1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"x"}'}}]
        self.assertEqual(client.parse_response(envelope(calls=calls))["tool_calls"], calls)
        with self.assertRaises(ModelProtocolError):
            client.parse_response(envelope(calls=calls + calls))

    def test_json_actions_only_accept_structured_tool_or_final(self):
        client = InternalHTTPModel(config(protocol="json_actions"))
        response = client.parse_response(envelope(json.dumps({"action": "tool", "name": "write_file",
                                                              "arguments": {"path": "outputs/x", "content": "ok"}})))
        self.assertEqual(response["tool_calls"][0]["function"]["name"], "write_file")
        self.assertEqual(client.parse_response(envelope('{"action":"final","answer":"done"}'))["content"], "done")
        for text in ("not json", "[]", '{"action":"shell","code":"print(1)"}', '{"action":"tool","name":"x","arguments":"bad"}'):
            with self.subTest(text=text), self.assertRaises(ModelProtocolError):
                client.parse_response(envelope(text))

    def test_json_mode_does_not_send_native_tools_fields(self):
        client = InternalHTTPModel(config(protocol="json_actions"))
        payload = client.build_payload([{"role": "tool", "content": '{"ok":true}'}], [{"type": "function"}])
        self.assertNotIn("tools", payload)
        self.assertTrue(all(m["role"] != "tool" for m in payload["messages"]))
        self.assertIn("TOOL_RESULT", payload["messages"][-1]["content"])

    def test_transport_bounds_and_no_sdk(self):
        client = InternalHTTPModel(config(max_response_bytes=1024))
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b"x" * size
        with patch.object(client.opener, "open", return_value=Response()), self.assertRaises(ModelProtocolError):
            client.complete([], [])

    def test_protocol_error_repair_is_bounded(self):
        class BrokenModel:
            def complete(self, messages, tools):
                raise ModelProtocolError("bad")
        base = Path(__file__).resolve().parent.parent / ".test-workspace"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as root:
            result = Agent(Runtime(root), BrokenModel()).run("test")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["steps"], 3)

    def test_production_modules_import_only_stdlib_or_this_package(self):
        import ast
        import sys
        package = Path(__file__).resolve().parent.parent / "internal_harness"
        for path in package.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [name.name.split(".")[0] for name in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    self.assertIn(name, sys.stdlib_module_names | {"internal_harness"}, (path, name))


if __name__ == "__main__":
    unittest.main()
