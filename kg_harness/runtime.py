import inspect
import json
from pathlib import Path
import typing

from .execution import Executor
from .files import Workspace
from .kg import KGStore


def schema_for(annotation):
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if typing.get_origin(annotation) is list:
        return {"type": "array", "items": schema_for(typing.get_args(annotation)[0])}
    raise TypeError(f"Unsupported tool type: {annotation}")


class Runtime:
    def __init__(self, root: str | Path, execution: str = "disabled", image: str = "python:3.12-slim"):
        self.workspace = Workspace(root)
        self.kg = KGStore(self.workspace.root / ".state" / "kg.sqlite3")
        self.executor = Executor(self.workspace, execution, image)
        # Explicit registry: model cannot select arbitrary Python attributes/functions.
        self.tools = {method.__name__: method for method in (
            self.workspace.list_files, self.workspace.read_file, self.workspace.search_files,
            self.workspace.write_file, self.workspace.edit_file,
            self.kg.list_versions, self.kg.search_kg, self.kg.get_record,
            self.kg.compare_versions, self.export_comparison,
        )}
        if execution != "disabled":
            self.tools["run_command"] = self.executor.run_command

    def schemas(self):
        schemas = []
        for name, function in self.tools.items():
            signature = inspect.signature(function)
            hints = typing.get_type_hints(function)
            properties = {key: schema_for(hints[key]) for key in signature.parameters}
            required = [key for key, param in signature.parameters.items() if param.default is inspect.Parameter.empty]
            schemas.append({"type": "function", "function": {
                "name": name, "description": inspect.getdoc(function) or name,
                "parameters": {"type": "object", "properties": properties,
                               "required": required, "additionalProperties": False}}})
        return schemas

    def call(self, name: str, arguments: dict):
        try:
            if name not in self.tools:
                raise ValueError(f"Unknown or disabled tool: {name}")
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object")
            function = self.tools[name]
            bound = inspect.signature(function).bind(**arguments)
            hints = typing.get_type_hints(function)
            for key, value in bound.arguments.items():
                annotation = hints[key]
                if typing.get_origin(annotation) is list:
                    valid = isinstance(value, list) and all(type(item) is str for item in value)
                else:
                    valid = type(value) is annotation
                if not valid:
                    raise ValueError(f"Invalid type for {key}")
            return {"ok": True, "result": function(**arguments)}
        except Exception as error:
            return {"ok": False, "error": type(error).__name__, "message": str(error)}

    def export_comparison(self, old: str, new: str, prefix: str = "outputs/comparison") -> dict:
        """Export complete graph differences to JSON and Markdown. Refuses to overwrite existing outputs."""
        json_path = self.workspace.resolve(prefix + ".json", write=True)
        md_path = self.workspace.resolve(prefix + ".md", write=True)
        if json_path.exists() or md_path.exists():
            raise FileExistsError("Choose a new report prefix; existing reports are preserved")
        summary = self.kg.comparison_summary(old, new)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents accidental overwrites. On failure remove partial pair.
        created = []
        try:
            with json_path.open("x", encoding="utf-8") as data:
                created.append(json_path)
                with md_path.open("x", encoding="utf-8") as report:
                    created.append(md_path)
                    report.write(f"# KG 版本差异：{old} → {new}\n\n")
                    report.write("这是知识图谱记录的差异，不是经原文核验的 JEDEC 修订结论。\n\n")
                    report.write("对齐方式：精确 stable_key；不推断重命名、拆分或合并。\n\n")
                    report.write(f"统计：`{json.dumps(summary, ensure_ascii=False)}`\n\n")
                    data.write('{"summary":' + json.dumps(summary, ensure_ascii=False) + ',"changes":[')
                    first = True
                    for item in self.kg.differences(old, new):
                        if not first:
                            data.write(",")
                        json.dump(item, data, ensure_ascii=False)
                        first = False
                        report.write(f"## {item['change']} · {item['kind']} · {item['key']}\n\n")
                        report.write("变化字段：" + ", ".join(item["changed_fields"]) + "\n\n")
                        for side in ("before", "after"):
                            record = item[side]
                            if record:
                                report.write(f"{side}：版本 `{record['version']}`，位置 `{record['pointer']}`\n\n")
                                report.write("```json\n" + json.dumps(record["body"], ensure_ascii=False, indent=2)
                                             + "\n```\n\n")
                    data.write("]}")
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return {"summary": summary, "files": [prefix + ".json", prefix + ".md"]}
