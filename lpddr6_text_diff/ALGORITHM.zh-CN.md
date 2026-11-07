# 具体算法：先匹配，再比对

## 1. 明确推荐

推荐首期采用：**章节约束 + 唯一精确匹配锚点 + 词面候选 + text encoder 补充候选 + 段落组对齐；匹配后使用 token diff + 要求字段检查 + 内部模型/人工语义核查。**

text encoder（文本向量编码器）用于寻找“这段改写对应旧版哪段”，不是最终判定“规范有没有改变”。不要求第一天就上 encoder：先做词面和结构基线，如果改写、移动的候选召回不足，再测加入 encoder 的增益。不要预设它一定更好。

当前已经运行的是本文第 8 节的标准库实验，没有实际 JEDEC 输入，也没有运行 text encoder 或真实大模型。完整算法是实现规格，不应把实验脚本当成生产 diff 引擎。

| 环节 | 首选算法 | 作用 |
|---|---|---|
| 版本内文本指纹 | SHA-256 + 原文确认 | 找完全一致的候选，重复句不能直接锁定 |
| 词面候选召回 | BM25；小章可直接比较全部段落 | 数字、符号、命令和术语匹配 |
| 改写候选召回 | 本地 bi-encoder + 归一化向量余弦 | 补充低词面重合的候选 |
| 候选排序 | 词面、章节上下文、术语、可选向量联合评分 | 识别同一内容的两版，不判等价 |
| 段落组选择 | 局部带拆合的动态规划 + 全局移动回查 | 避免独立贪心匹配冲突 |
| 表面编辑 | token 级 SequenceMatcher，autojunk=False | 输出插入、删除、替换跨度 |
| 要求差异 | 结构化槽位比较 + 条件检查 + 证据核查 | 区分改写、要求变化、待确认 |

BM25、encoder、模型均可在公司内部运行；无需 Claude Code/Codex SDK 或其模型 API。如果公司已有 embedding 服务，优先用它做试验。没有时可将 BAAI/bge-m3 作为本地候选模型之一，其模型卡提供本地加载方式；这不表示它在 JEDEC 上已经胜出。[模型卡](https://huggingface.co/BAAI/bge-m3)

Cross-encoder 是可选的第二阶段排序器：将两个候选文本一起输入，比对其相关性。首期可不上，等候选竞争确实成为瓶颈再测试。检索相关性分数仍不等于规范等价概率。[Sentence Transformers 官方说明](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)

## 2. 两个分数必须分开

```text
alignment_score(A, B): 两段是否是同一内容在不同版本的对应位置？
semantic_result(A, B, context): 对应要求相同、改变，还是无法确定？
```

例如 `shall issue CMD_X` → `shall not issue CMD_X`：匹配分应很高，因为它们很可能就是同一条款的两个版本；语义比较则要抓住否定变化。因此**不要在匹配阶段把否定、数值变化当成排除对应关系的理由**。也不要将相似度 0.99 显示为“99% 没有变化”。

## 3. 第一阶段：匹配的可实现步骤

### 3.1 处理单位与章节映射

每个版本保留章节树，段落、列表项、脚注使用版本内唯一 ID。只修复明确的排版空白；命令标识、大小写、运算符、数字、单位、否定词全部保留。原文和规范化文本独立保存。

章节先匹配唯一精确标题及其父路径；对其余章节使用标题词面、章节对象集合、唯一正文指纹覆盖率生成候选。重编号不影响对象身份。父章节映射是软约束；疑似移动章节允许跨父节点找候选。无法确认的章节继续保留多个候选，不能提前丢弃其段落。

### 3.2 生成候选

在候选对应章节内：

1. 收集原文/安全规范化后完全相同的段落。只有唯一、对象与章节上下文不冲突时才作为强锚点；重复模板句仍需排序。
2. 每个旧段落用 BM25 找新版 top 10，反向同样检索；这是初始候选预算，不是已调优值。
3. 可选 encoder 检索 top 10，与词面候选取并集。BM25 数值与余弦分数不要直接相加；可先仅用排名召回，再统一打分。
4. 为每个候选加入同一小节中相邻的 2 段和 3 段组合，反向也加入，支持 1:N/N:1。正文过长时按句切片，不能超过模型上限后静默截断。
5. 局部未解决内容跨章节再找候选，以识别移动。全局候选搜索失败仍不自动确认删除；须检查解析缺损、章节拆合和低分候选。

段落数量不大的一章，可直接全比较而不做 top-K；先测实际长度分布和耗时。数百 MB 文件不要直接构造整个文档 N×M 的矩阵。

### 3.3 候选评分与参数

首期无 encoder 的可运行基线：

```text
L = mean(SequenceMatcher(tokens(A), tokens(B)).ratio(),
         SequenceMatcher(tokens(B), tokens(A)).ratio())
C = 同样算法计算章节标题词面相似度
S0 = 0.70 * L + 0.30 * C - 0.02 * (组合段落总数 - 2)
```

1:1 组合总数为 2，复杂度惩罚为 0；1:2 惩罚 0.02。这些是可复现的试验起点。标题相同但正文不同不能仅靠 C 确认匹配。

加入 encoder 时，建议在同一开发集比较以下候选排序配置：

```text
S1 = 0.45 * L + 0.20 * C + 0.35 * E - complexity_penalty
E = clip(cosine(normalized_embedding(A), normalized_embedding(B)), 0, 1)
```

这是待实测的融合基线，不是论文推荐比例或已经验证的参数。正文 embedding 与章节标题分开，避免长标题掩盖段落内容。若增加术语特征，应通过消融检查收益，并重新调阈值，不能继续沿用旧阈值。

实验脚本以 0.50 为候选保留门槛，**不是自动确认门槛**。生产先把排序结果视为 proposed。开发集上扫 `S` 门槛和第一/第二候选分差（margin），在对齐精确率满足要求的条件下最大化自动覆盖率。建议试验网格：S 从 0.50 到 0.95，步长 0.05；margin 从 0 到 0.20，步长 0.05。未验证前不把 0.85 等任意数值写成可信默认。

### 3.4 选择不冲突的段落组

顺序大体一致的小节，用动态规划，令 `F(i,j)` 表示消费旧版前 i 段和新版前 j 段的最小代价：

```text
F(i,j) = min(
  F(i-1,j) + gap,
  F(i,j-1) + gap,
  F(i-a,j-b) + (a+b)/2 * (1 - S(group_old, group_new))
)
(a,b) ∈ {(1,1),(1,2),(2,1),(1,3),(3,1),(2,2)}
F(0,0)=0; F(i,0)=i*gap; F(0,j)=j*gap
```

只对召回的有效组或小章的全组合计算匹配转移。`gap=0.25` 可作为开发起点，并与分值阈值一起调优；gap 是暂时未匹配的代价，不是断言新增/删除。复杂度惩罚已包含在 S，不再重复扣分。

DP 不能独自解决跨章节移动。第一轮后把未匹配、低置信组及其竞争候选放回全局图；对纯 1:1 子问题可以使用带 dummy unmatched 节点的最大权匹配，多段组用带成员互斥约束的选择，或保守留待复核。**实验脚本仅演示单案例候选排序，没有实现这个全局 DP/约束求解。**

## 4. 第二阶段：匹配后怎么比对

### 4.1 表面 diff：任何原文差异都可记录

已匹配段落组先按技术 token 切分，保留 token→原文字符跨度。使用 `SequenceMatcher(..., autojunk=False).get_opcodes()` 得到 equal/insert/delete/replace。先段落组后句子再 token，避免整章字词交叉对齐。

它适合 Python 首期实现和可读高亮，但不保证最小编辑脚本。若需要最短插删序列，可另测 Myers 算法；不能把 SequenceMatcher 宣称为 Myers 或最小编辑距离。关闭 autojunk 是为了不让技术文档中的高频重复 token 被自动当作匹配噪声。[Python 官方文档](https://docs.python.org/3/library/difflib.html)

可以展示“字词编辑占比”：令 equal 操作中保留的 token 数为 M，两侧 token 数为 n、m，定义 `edit_fraction = 1 - 2M/(n+m)`，两侧都为空则为 0。这只描述表面改写量，**不作为规范变化程度或业务风险分数**。算法和分词版本要固定。

### 4.2 语义 diff：不因一个字符不同就判实质变化

把每条要求抽取为：主体、动作、对象、模态、否定、条件逻辑树、量词、数值约束、单位、时序关系、例外、引用目标；每个槽位带原文跨度。先匹配同组中的要求，再比较槽位。

| 规则 | 可以得到什么结论 |
|---|---|
| raw_text 相同且有效上下文/引用依赖均确认不变 | 正文及其已检查的含义不变 |
| 只发生已批准的换行/空白修复且依赖不变 | 排版差异；原始差异仍可展开 |
| 同参数同适用域的已验证数值/边界约束不同 | 确认要求变化，输出具体字段 |
| 单位换算后约束完全相同，其他槽位及依赖一致 | 等价候选；明确单位维度和舍入条件 |
| 否定、模态、量词、AND/OR、时序词变化 | 必须进入语义检查；词出现不等于其作用域已正确解析 |
| 章节号/表号改变但引用对象确认相同 | 引用编号变化，不自动判规范改变 |
| 文字相同，但上级条件/定义/引用目标变化 | 触发上下文比较，不能走“相同”快速路径 |
| 槽位提取不完整、引用缺失、模型与规则冲突 | unresolved，交复核 |

如果要求可可靠形式化，就直接比较约束。例如旧 `delay>=10 ns`，新 `delay>=12 ns`：给出 delay=11 ns 作为区分两版的例子。主被动改写、代词指代、复杂例外等无法可靠规则化时，把新旧要求连同上下文交内部模型，并验证其证据；不能因为“字段提取器没发现差异”就认定等价。

因此，**匹配上后可以直接做判断，但判断器必须看两侧原文和依赖；不能直接用匹配分数判断。** 对结构化约束，不必让 LLM 重做每个可确定计算；对复杂语义，也不必指望几条正则包办。

## 5. 是一点不同就算 diff，还是分程度展示

底层记录全部原文编辑；面向业务按以下结果层次展示。它们是变化类别，不是线性的风险评分：

| 展示层 | 判定 | 默认展示 |
|---|---|---|
| D0 无变化 | 内容及已检查依赖相同 | 隐藏详情，可查覆盖 |
| D1 排版变化 | 仅安全空白/换行等变化 | 灰色折叠 |
| D2 等价改写 | 文字改了，要求或陈述含义确认等价 | 蓝色折叠，显示改写及证据 |
| D3 含义变化 | 要求/定义/信息发生实质变化 | 展开，说明改变的槽位 |
| U 待确认 | 匹配、上下文或含义无法可靠判定 | 独立醒目队列，不能折叠为无变化 |

另有两个正交标签：结构标签（移动/拆分/合并/新增/删除）与业务优先级（高/中/低/未评估）。D3 再分 requirement_changed 与 information_changed，不把信息性改写都当规范变化。新增/删除还要区分新增解释和新增要求。

一个 `not` 变化可以是 D3 高优先级，整段主动句改被动句可以是 D2；不能用“改动 5% 以下轻微、50% 以上严重”决定工程影响。

这些 D 标签是展示派生字段：底层继续使用已有 semantic_label、structural_changes、severity、review_status。D0/D1/D2 都可能对应 equivalent，具体由文本相同/排版/改写字段区分；U 对应 unresolved。

## 6. 推荐决策伪代码

```python
for group in alignment_groups:
    if not group.alignment_confirmed:
        emit(group, display="U", reason="alignment_uncertain")
        continue
    edits = token_diff(group.old_raw, group.new_raw)
    dependencies = compare_effective_context_and_references(group)
    if dependencies.incomplete:
        emit(group, edits=edits, display="U", reason="missing_context")
        continue
    if raw_equal(group) and dependencies.equivalent:
        emit(group, display="D0", structural_tags=group.structural_tags)
        continue
    if only_safe_layout_edits(edits) and dependencies.equivalent:
        emit(group, display="D1")
        continue
    requirements = extract_and_align_requirements_with_evidence(group)
    result = compare_verified_slots(requirements, dependencies)
    if result.inconclusive:
        result = internal_model_review(group, requirements, dependencies)
    result = validate_quotes_and_rule_consistency(result)
    emit(group, edits=edits, result=result)  # D2 / D3 / U
```

这是业务流程伪代码，其中抽取、对齐及模型复核函数尚未实现。有效上下文不仅指父章节，还包括列表引导句、指代先行词、定义及引用目标。

## 7. 怎样选择 encoder，而不是凭感觉

在真实开发集上，使用同一候选预算比较：

1. BM25/词面 + 章节结构。
2. encoder + 章节结构。
3. BM25 与 encoder 候选并集 + 统一排序。
4. 方案 3 + 可选 cross-encoder 重排。

指标先看候选全成员 Recall@K、组对齐精确率、改写/移动子集召回，再看耗时/内存。语义阶段固定同一个判断器，避免把判断器提升误算为 encoder 收益。模型及规则阈值均在开发集选定，在冻结测试集只跑一次最终评价。

若结构词面方案已达到召回目标，且 encoder 只增加延迟，就先不加；若对低词面重合的改写有稳定增益，保留混合召回。当前没有本地 sentence-transformers/torch 模型环境，因此不提供 encoder 胜出的实测结论。

## 8. 本次真实运行的合成诊断

脚本：[compare_baselines.py](experiments/compare_baselines.py)；逐案例结果：[results.synthetic.json](experiments/results.synthetic.json)。15 例包含不变、空白、改写、数字、否定、边界、模态、条件、等价单位换算、引用重编号、继承条件变化、重复模板句、章节移动、拆分、删除。样例全部为人工构造，非真实 JEDEC 文本。

```powershell
python lpddr6_text_diff/experiments/compare_baselines.py
```

### 匹配实验：14 例有对应内容，另 1 例删除

| 方法 | 对应成员集合完全正确 | 删除例保持未匹配 |
|---|---:|---|
| 唯一精确匹配（规范化空白） | 4/14 | 是 |
| 词面 SequenceMatcher | 11/14 | 是 |
| 词面 + 标题 | 12/14 | 是 |
| 词面 + 标题 + 相邻段落组合 | 13/14 | 是 |

所有方法共用手工候选池及预先给定的标题，未做整文档候选检索和冲突求解；删除例未匹配只是预期状态，不是生产删除认证。13/14 不是泛化准确率。此实验说明结构和拆合值得实现，不证明 encoder 没用。重复模板句也展示了：精确匹配可能锁到另一个章节的相同句子。

### 比对实验：给定正确对齐，7 例实质要求变化

| 判定方法 | 正确发现 TP | 误报 FP | 漏检 FN |
|---|---:|---:|---:|
| 规范化后文字不同即认为要求变化 | 6 | 4 | 1 |
| 词面相似度 <0.85 才认为变化 | 2 | 3 | 5 |
| 词面相似度 <0.90 才认为变化 | 2 | 4 | 5 |
| 词面相似度 <0.95 才认为变化 | 6 | 4 | 1 |

这是词面分数实验，**不能拿来宣称实测了 encoder 阈值**。改写、等价单位换算和引用重编号可触发误报；文字不变的继承条件变化会漏检。完整规则+模型判断器尚未实测，不声称它已消除这些错误。

下一步应拿真实数据补足三个输入：原始段落及章节元信息、上下文/引用关系、专家标注的少量匹配与语义样本。用这些检验本方案，而不是继续凭合成样例调出漂亮数字。
