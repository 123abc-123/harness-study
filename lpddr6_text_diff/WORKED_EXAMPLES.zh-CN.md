# 实际运行的逐条匹配结果

这里的“实际运行”指运行了仓库中的 Python 程序并保存其输出，**不是拿真实 LPDDR6 JEDEC 文件跑出的结果**。目前工作区只有标明为 synthetic 的 JEDEC 风格 JSON 和本目录人工构造的 15 个英文句子，没有用户的两个真实解析文件。以下句子、参数与章节都是合成例子，不得当作 JEDEC 原文或性能证明。

复现：

```powershell
python lpddr6_text_diff/experiments/trace_examples.py
```

程序：[trace_examples.py](experiments/trace_examples.py)。完整机器输出：[traces.synthetic.json](experiments/traces.synthetic.json)。在 `harness_v2/.venv` 中以 `python -S` 运行，未调用模型或网络。

## 分数究竟怎么算

下面使用现有实验中的 `lexical_context_groups`：

```text
L = 新旧正文 token 的对称 SequenceMatcher 比率
C = 新旧小节标题 token 的对称 SequenceMatcher 比率
S = 0.70 × L + 0.30 × C − 0.02 × (组内段落数 − 1)
```

这里组内段落数是**新侧候选组**长度；单段惩罚 0，两段惩罚 0.02。程序先按 S 从高到低排，最高分至少 0.50 才返回候选；低于 0.50 返回未匹配。这个门槛只是诊断配置，不代表已在 JEDEC 上校准，也不代表“分数超过 0.50 就确认对应”。案例之间各有小型手工候选池，未运行整文档全局匹配。

输出中的 `gold_ids` 和 `expert_label_in_fixture` 是编写样例时人工设定的期望答案，用来判断程序是否正确；不是模型自己证明的结果。`narrow_rule` 是只覆盖几个简单句型的可执行规则。它输出 `unresolved` 时，不能将人工期望标签冒充程序的语义结论。

## 例 1：一个数字改动，匹配正确且规则发现变化

旧段 `old`：

> The controller shall wait at least 10 ns after CMD_X.

新候选 `target`：

> The controller shall wait at least 12 ns after CMD_X.

另有不相关候选 `other`：“The device shall remain in State_Z.”

| 候选 | L | C | S | 结果 |
|---|---:|---:|---:|---|
| target | 0.9091 | 1.0000 | **0.9364** | 选中 |
| other | 0.3333 | 0.0000 | 0.2333 | 排除 |

例如 target 的分数为 `0.70×0.9091 + 0.30×1 = 0.9364`（四舍五入）。匹配确定的是“这两句对应”；token diff 的实际输出是 `replace 10 → 12`。窄规则识别为 `requirement_changed / minimum_wait: 10 ns → 12 ns`。在假设其余条件相同的这个合成句子里，11 ns 满足旧约束、不满足新约束。

## 例 2：只插入一个否定词，匹配分很高，含义却相反

旧：`The controller shall issue CMD_X.`

新：`The controller shall not issue CMD_X.`

| 候选 | L | C | S |
|---|---:|---:|---:|
| target | 0.9231 | 1.0000 | **0.9462** |
| other | 0.4615 | 0.0000 | 0.3231 |

程序选中 target，token diff 是 `insert not`，窄规则输出 `requirement_changed / polarity: false → true`。所以高匹配分表示“找到对应句”，绝不能解释成“94.62% 语义相同”。

## 例 3：正文完全一样，但上级适用条件改变

两版正文完全一样：`The controller shall wait at least 10 ns after CMD_X.`

旧章节上下文：`This section applies in Mode_A.`；新章节上下文：`This section applies in Mode_B.`

程序对正文 target 的 L、标题 C、总分 S 都算出 **1.0000**，token diff 为空。窄规则仍输出 `requirement_changed / inherited_condition: Mode_A → Mode_B`。这说明只在段落本身上做 hash 或文本 diff 会漏掉变化；真实 JEDEC 中还需检查引导句、引用目标和定义等依赖。

## 例 4：段落拆成两段，单段匹配会少一半

旧段：`The controller shall wait at least 10 ns after CMD_X. The device shall remain in State_Z.`

新版相邻两段：

- `a`：`The controller shall wait at least 10 ns after CMD_X.`
- `b`：`The device shall remain in State_Z.`

| 候选 | L | C | S | 结果 |
|---|---:|---:|---:|---|
| a+b | 1.0000 | 1.0000 | **0.9800** | 选中两段组 |
| a | 0.7586 | 1.0000 | 0.8310 | 只能覆盖旧段一部分 |
| b | 0.5600 | 1.0000 | 0.6920 | 只能覆盖旧段一部分 |

程序选中 `['a','b']`，得到 `same_local_text`；结构标签应是 `split`。这里本地正文相同，但 `same_local_text` 不代表程序验证了全部外部上下文。

## 例 5：另一章有完全相同的模板句，标题帮忙避免错配

旧正文：`Wait until the operation completes.`，旧标题 `Calibration`。

新候选 `other` 正文**完全相同**，但标题是 `Initialization`；候选 `target` 正文改写为 `Wait for the operation to finish.`，标题是 `Calibration`。

| 候选 | L | C | S | 结果 |
|---|---:|---:|---:|---|
| target | 0.6154 | 1.0000 | **0.7308** | 选中 |
| other | 1.0000 | 0.0000 | 0.7000 | 未选中 |

只做全文精确匹配会选错 `other`；词面＋标题的分数让程序选对 `target`。不过两者只差 **0.0308**，这个小差距在真实系统里应标记“竞争候选，待确认”，而非仅凭 top-1 自动锁定。程序的窄规则对这次改写输出 `unresolved`；样例作者认为等价，但**程序没有证明等价**。

## 例 6：改写幅度大，正确候选排第一却被门槛拒绝

旧：`The controller shall wait at least 10 ns after CMD_X.`

新 `target`：`Following CMD_X, a minimum delay of 10 ns is required of the controller.`

| 候选 | L | C | S | 结果 |
|---|---:|---:|---:|---|
| target | 0.2308 | 1.0000 | **0.4615** | 排第一，但未达到 0.50 |
| other | 0.3333 | 0.0000 | 0.2333 | 未选中 |

程序最终输出 `selected_ids=[]` 和 `unmatched`。人工给定的对应组是 `['target']`，所以这是**明确的漏匹配**，不能把空结果直接解释成删除。Text encoder 或 cross-encoder 是否能补回，需要在实际数据上测；目前没有实测结论。

## 例 7：没有找到对应内容，只能先标未匹配

旧：`The controller shall wait at least 10 ns after CMD_X.`；新版池里只有不相关的 `other`。

`other` 的 L=0.3333、C=0、S=0.2333，程序返回 `selected_ids=[]`。这个合成样例的人工答案是“删除”，但程序只输出 `unmatched`，原因是未进行跨章节移动和全局候选搜索。真实流程完成全局回查及解析完整性检查后，才能进一步确认删除。

## 从这些运行结果得到的实现选择

1. 第一阶段把精确匹配当锚点候选，把词面和章节上下文一起用；相邻段落组能处理拆分。竞争候选小分差必须保留复核。
2. 第二阶段单独看 token 编辑和要求字段。数字、否定、上级条件有可执行检查；复杂改写继续保持 unresolved，交内部模型和专家核对证据。
3. 对于例 6，先在真实开发集测 BM25/词面与 encoder 候选召回；如果 encoder 补回这类案例且误配可控，再加入混合候选。

本报告没有真实 LPDDR6 解析文件上的结果。若将来提供两版 JSON，应先按 [数据契约](DATA_CONTRACT.zh-CN.md) 适配、抽完整章节做盲标，再报告真实案例及指标。
