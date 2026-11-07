# 输入输出契约草案 v0.1

这是供后续适配的建议结构，不要求修改原解析器，也不是已实现的 JSON Schema 验证器。适配层负责把现有章节/段落元信息映射到这里。现有 KG 可保留，正文证据单独建索引。

## 输入

```text
document: document_id, standard_id, revision, source_sha256, parser_version
sections[]: section_id, parent_id, number, title, order
blocks[]:
  block_id, section_id, kind, order, raw_text
  source: file_id, page?, bbox?, parser_path?
  references[]: target_object_id, relation, provenance, evidence_span
objects[]: object_id, kind(table/figure/footnote/definition), source, content
```

ID 在版本内唯一，以 document_id + block_id 联合标识来源；跨版本对应关系写到 alignment_group，不从编号猜稳定键。页码明确使用 PDF 页序还是印刷页码，bbox 指定页面坐标单位与原点。缺失时保留 null，不制造位置。

原文字符跨度使用 **Unicode code point，0 起始，end 不包含**。Python 字符串切片按此处理；前端 JavaScript UTF-16 索引必须转换，特别注意补充平面字符。跨度引用的是未修改的 raw_text，不是匹配时的规范化文本。

## 运行与对齐

```text
run: run_id, old_document_id, new_document_id, input_hashes,
     parser_versions, rules_version, model_version, prompt_version,
     scope, started_at, finished_at, coverage, unresolved_counts
alignment_group:
  group_id, old_block_ids[], new_block_ids[], structural_changes[],
  candidates[], decision_status, method, review_history[]
```

旧侧为空表示新增，新侧为空表示删除；两侧同时为空非法。新增/删除仅在完成匹配检查后确认。`decision_status` 建议取 proposed / confirmed / unresolved，`confirmed` 的确认主体另记 rule/model/human，不混淆人工认可。

## 变化事件

实际 JSON 样例见 [change_event.json](examples/change_event.json)。

必要字段：event_id、alignment_group_id、old/new document_id、primary_section、两侧 section_path 与 block_id、结构标签、语义标签、变化槽位、证据、审核状态。可选字段：形式化约束、反例、影响关系、经校准的 confidence。

`semantic_label` 枚举：equivalent、requirement_changed、information_changed、unresolved。

`origin` 枚举：direct、contextual、indirect_reference。`root_event_id` 用于关联根变更，不表示该影响已经确认；影响边另外记录 possible / confirmed / rejected。

`severity` 枚举：high、medium、low、unassessed。`review_status` 枚举：pending、accepted、corrected、rejected。模型结果默认 pending；示例中标签是人工设定的期望结果，不是模型实测。

单条证据结构：document_id、block_id、start、end、quote、role。role 可为 old_requirement / new_requirement / inherited_condition / reference / definition。引用跨度和 quote 必须一致。新增事件旧侧要求证据可为空，删除事件新侧可为空，但保留匹配检查结果。

## 必须验证的约束

1. 所有引用 ID 存在且属于正确版本；每段都有账本状态；待匹配内容没有被静默排除。
2. 0 ≤ start < end ≤ len(raw_text)，且 raw_text[start:end] == quote。
3. 事件必须属于已有对齐组；旧/新证据分别属于相应组或明确标注的上下文依赖。
4. 单侧为空与 added/deleted 标签一致；同一段重复出现在冲突组时阻止自动确认。
5. 槽位变化有原文或上下文来源；提取不到的值用 unknown，不能伪造默认值。
6. unresolved 事件携带原因；任何概率值须有校准说明，否则留空。
7. 章节汇总对唯一 event_id 去重；根事件与影响关系分列。
8. 导出包含 run_id 和输入 hash，保证结果能对应到具体解析版本。

样例将 input_blocks 内嵌以便独立检查证据；生产环境应按 ID 引用已存储的输入，避免复制数百 MB 原文。原始文件、缓存、日志和运行输出应留在内部工作区；本公开目录只存方案与合成样例。
