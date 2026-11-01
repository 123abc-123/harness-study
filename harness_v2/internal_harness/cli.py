"""Command line entry point; model endpoints must come from an explicit config file."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from .agent import Agent, ScriptedDemoModel
from .model import InternalHTTPModel, ModelConfig, origin
from .runtime import Runtime


def initialize(runtime, examples):
    results = []
    for name in ("jedec_A.json", "jedec_B.json"):
        source = examples / name
        target = runtime.workspace.root / "inputs" / name
        if not target.exists():
            shutil.copyfile(source, target)
        elif target.read_bytes() != source.read_bytes():
            raise ValueError(f"Refusing to overwrite input {target.name}")
        results.append(runtime.kg.import_file(target))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="V2: independent internal-model KG harness")
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--executor", choices=("disabled", "docker", "trusted-local"), default="disabled")
    parser.add_argument("--image", default="python:3.12-slim")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "demo"):
        command = sub.add_parser(name)
        command.add_argument("--examples", default=str(Path(__file__).resolve().parent.parent / "examples"))
    imp = sub.add_parser("import")
    imp.add_argument("path")
    sub.add_parser("versions")
    ask = sub.add_parser("ask", help="Evidence lookup; --config enables internal-model synthesis")
    ask.add_argument("--version", required=True)
    ask.add_argument("--question", required=True)
    ask.add_argument("--config")
    compare = sub.add_parser("compare")
    compare.add_argument("--old", required=True)
    compare.add_argument("--new", required=True)
    compare.add_argument("--output")
    tool = sub.add_parser("tool")
    tool.add_argument("name")
    tool.add_argument("arguments", nargs="?", default="{}")
    agent = sub.add_parser("agent", help="Run against an explicitly configured internal service")
    agent.add_argument("task")
    agent.add_argument("--config", required=True)
    agent.add_argument("--max-steps", type=int, default=20)
    doctor = sub.add_parser("doctor", help="Validate configuration locally, without model requests")
    doctor.add_argument("--config")
    args = parser.parse_args(argv)
    try:
        runtime = Runtime(args.workspace, args.executor, args.image)
        if args.command == "init":
            result = initialize(runtime, Path(args.examples))
        elif args.command == "demo":
            initialize(runtime, Path(args.examples))
            prefix = "outputs/demo-" + uuid.uuid4().hex[:8]
            executable = None
            if args.executor != "disabled":
                executable = "python" if args.executor == "docker" else sys.executable
            result = Agent(runtime, ScriptedDemoModel(prefix, executable)).run("离线演示：查询 KG、写入和修改文件、导出差异")
            result["mode"] = "deterministic_demo_not_llm"
        elif args.command == "import":
            result = runtime.kg.import_file(runtime.workspace.resolve(args.path))
        elif args.command == "versions":
            result = runtime.kg.list_versions()
        elif args.command == "ask":
            if args.config:
                runtime.kg.search_kg(args.version, args.question, limit=1)  # Validate pinned version.
                model = InternalHTTPModel(ModelConfig.load(args.config))
                result = Agent(runtime, model).run(
                    f"只查询版本 {args.version}。回答以下问题，引用记录 key 和 source pointer；证据不足需明确说明：\n{args.question}")
            else:
                result = {"mode": "keyword_evidence_only", "question": args.question,
                          **runtime.kg.search_kg(args.version, args.question),
                          "note": "离线关键词证据，不是模型推理；自然语言问答请显式提供 --config。"}
        elif args.command == "compare":
            result = runtime.export_comparison(args.old, args.new, args.output or "outputs/diff-" + uuid.uuid4().hex[:8])
        elif args.command == "tool":
            result = runtime.call(args.name, json.loads(args.arguments))
        elif args.command == "doctor":
            result = {"runtime": "stdlib-only", "model_requests_sent": 0,
                      "executor": args.executor, "registered_tools": sorted(runtime.tools),
                      "python": sys.version.split()[0]}
            if args.config:
                config = ModelConfig.load(args.config)
                result["model_config"] = {"origin": origin(config.endpoint), "model": config.model,
                                          "protocol": config.protocol,
                                          "credential_present": bool(os.environ.get(config.auth_env, "")) if config.auth_env else None}
        else:
            if not 1 <= args.max_steps <= 100:
                raise ValueError("max-steps must be 1..100")
            model = InternalHTTPModel(ModelConfig.load(args.config))
            result = Agent(runtime, model, max_steps=args.max_steps).run(args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and (result.get("ok") is False or result.get("status") in
                                       ("failed", "step_limit", "context_limit") or
                                       args.command == "demo" and result.get("tool_errors", 0)):
            return 1
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
