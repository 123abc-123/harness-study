# KG JSON v1 数据契约

样例见 `examples/jedec_A.json` 和 `examples/jedec_B.json`，所有内容均为虚构。

根对象：`schema_version: 1`、`standard: string`、`version: string`、`sections: array`。
建议附 `provenance`，记录解析器、图算法及原文来源版本。

每个 section 包含：

- `stable_key`：必填、非空；同一语义章节跨版本保持稳定，同一版本内唯一。
- `number`、`title`、`text`：章节编号、标题和内容；不用于永久身份。
- `source`：原文文档、条款、页码等来源，形式暂不限定。
- `entities`：可选数组；每个实体有全版本内唯一的 `stable_key`。
- `relations`：可选数组；每条关系有唯一 `stable_key`、指向实体 stable_key 的 `source_id` 与 `target_id`，以及 `type`、`origin`。
- `subsections`：递归章节数组。

实体其他属性（min、max、unit、condition 等）原样保留。关系支持跨章节引用；悬空端点导致整次导入回滚。重复 key 导致导入回滚。相同版本相同源文件哈希重复导入幂等，不同内容禁止覆盖。

规范化记录以 `(version, kind, key)` 唯一定位。pointer 为源 JSON 的 JSON Pointer，section_key 定位所属章节。来源文件哈希保存在版本目录中。父章节由 parent_key 连接。

`NestedJSONAdapter.read()` 返回元数据与顶层章节迭代器；`records()` 产出 `(kind, key, section_key, pointer, body)`。将来变更 JSON，只需替换适配器并保留该协议。

当前不是通用 JSON Schema 验证器：仅检查关键标识、版本、重复 key 和关系端点等必要约束。真实数据接入后应增加类型、单位、必填字段和来源完整性验证。

大文件：可选 ijson 按顶层章节解析。一个顶层章节仍会完整驻留内存；若只有一个包含全图的大章节，应改为事件级解析或导入时转换为逐记录格式。禁止把当前实现宣传为任意大小 JSON 的恒定内存解析器。

比较默认稳定 key 已对齐；不做模糊匹配。source-only 变化不计为语义修改。其他字段使用 JSON 值比较，列表顺序变化可能被报告。没有数值精度归一、单位换算或自然语言语义等价判定。
