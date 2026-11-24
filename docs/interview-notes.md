# 材料计算 Agent 面试笔记

更新于 2026-11-24。前五节是项目速答，后面的题库有 40 道主问题，每道都有项目口述示范，以及答题抓手或追问。题目根据学习路线和公开面经改写，按与 Agent 应用研发、AI 后端和 Agent 平台岗的匹配度排序。标为「设计题」的能力用来讨论方案和取舍，项目经历以当前源码和可复现实验为准。

## 1. 检索为什么选中这个片段？

面试常从完整链路问起，再追问如何定位召回失败、切片断上下文以及回答没有使用证据的问题。

项目先按 Markdown 标题分段，再按重叠窗口切分长段。检索同时跑 BM25 和字符 n-gram 余弦匹配，用 Reciprocal Rank Fusion 合并名次，加领域短语重排并保留前三条。两套召回都弱时会过滤候选。没有候选时返回资料不足。真实模型模式校验引用 ID 是否属于本次候选，引用校验本身不能证明回答的每句话都有证据。

运行 `uv run --locked python -m materials_agent.evaluation --out var/retrieval-report.json` 查看逐题结果。本次固定题集有 12 道可答题和 2 道无关题。BM25 的 Recall@3 和 MRR 均为 0.5833，混合检索均为 1.0000，两种模式对两道无关题均返回空候选。题集与资料卡同域，其中若干短语用于调试规则，结果仅能说明当前小语料上的行为。字符 n-gram 是稀疏字面特征。语义 Embedding、ANN 向量库和交叉编码器精排可在更大的独立集上做对比。

来源：[RAG 链路](https://notes.kamacoder.com/llm/app/chain_of_rag.html) · [切片](https://notes.kamacoder.com/llm/app/how_to_chunking.html) · [Embedding](https://notes.kamacoder.com/llm/app/embedding.html) · [向量数据库](https://notes.kamacoder.com/llm/app/vector_database.html) · [检索优化](https://notes.kamacoder.com/llm/app/rag_optimization.html) · [RAG 评估](https://notes.kamacoder.com/llm/app/rag_evaluation.html)

## 2. 工具调用的执行权在哪里？

模型根据请求选择查资料、直接计算或先查再计算。Schema 约束路由和参数。LangGraph 定义查资料、审批和入队的依赖。复合请求永远经过人工审批，审批拒绝后没有计算任务。普通计算请求也可开启审批。检查点保留等待状态和已经取得的证据，批准后从原运行继续。

面试可进一步说明 ReAct 适合动态探索工具，固定依赖适合用可预测的图。当前项目是有条件分支的受控工作流。用户输入和文件内容只作为模型数据传入，后端只接受预定义动作。直接计算有 2 次尝试上限，工作流没有开放式代理循环。

来源：[结构化输出](https://notes.kamacoder.com/llm/app/structured_output.html) · [Function Calling](https://notes.kamacoder.com/llm/app/function_calling.html) · [Agent 与 Workflow](https://notes.kamacoder.com/llm/app/agent_vs_workflow.html) · [设计模式](https://notes.kamacoder.com/llm/app/react_reflection_planning.html) · [DAG](https://notes.kamacoder.com/llm/app/plan_execute_dag.html) · [故障与边界](https://notes.kamacoder.com/llm/app/agent_failure_modes.html)

## 3. Function Calling 和 MCP 是什么关系？

Function Calling 是模型按 Schema 提交结构化意图。本地 MCP 服务通过 stdio 让兼容客户端发现并调用工具。目前只暴露检索和任务查询。计算提交属于工作流的写入口，复合请求必须先批准。测试启动真正的 MCP 子进程，走了初始化、列工具和调用工具。MCP 工具使用只读数据库连接。

来源：[工具设计](https://notes.kamacoder.com/llm/app/agent_tool_design.html) · [MCP 与 Function Calling](https://notes.kamacoder.com/llm/app/mcp_protocol.html) · [MCP Python 官方 SDK](https://github.com/modelcontextprotocol/python-sdk)

## 4. 失败、重连和模型开销怎么定位？

运行 ID 记录路由、检索候选、引用、审批和入队。任务 ID 记录 worker 的领取、重试和结束事件。后台事件写入 SQLite，并用 SSE 推送。客户端可以用最后收到的事件 ID 补读。检查点存的是当前流程状态，资料索引提供领域知识，两者用途不同。超时和租约过期的重试通过稳定的任务标识与领取令牌约束，旧 worker 不能覆盖新结果。

可选模型模式分别限制路由和回答的输出 Token 数，同时记录模型名、节点耗时及供应商回传的用量。供应商未回传的数据保留为空。真实供应商尚未联调。SSE 传输的是任务事件，模型接口仍一次返回结构化结果，因此没有模型 TTFT/TPOT 实测。

本地检索 HTTP 冒烟压测做了 40 次请求、4 并发、100 ms 的示例 SLO，本次 40 次成功，P50 为 3.71 ms、P95 为 6.15 ms。脚本同时报告完成吞吐和 SLO 内吞吐。短时单机数据仅供复现测量方法。

来源：[同步、异步和流式](https://notes.kamacoder.com/llm/app/streaming_output.html) · [Token、成本和延迟](https://notes.kamacoder.com/llm/app/token_cost_latency.html) · [状态和记忆](https://notes.kamacoder.com/llm/app/agent_memory.html) · [可观测性](https://notes.kamacoder.com/interview/llm/agent_harness_observability_interview.html) · [Agent 评估](https://notes.kamacoder.com/llm/app/agent_evaluation.html) · [压测](https://notes.kamacoder.com/llm/app/stress_testing.html)

## 5. 模型训练为什么不在这个项目里？

这个项目使用已有模型。RAG 用于材料事实和可追溯引用，规则与 Schema 用于可确定的约束。如果有足够标注样本，且对照实验发现提示、工具定义与模型选择仍无法解决稳定的行为偏差，再讨论 SFT。LoRA/QLoRA 是降低适配代价的方法。DPO 和 RLHF 用于偏好与行为对齐。面试另外复习 QKV、位置编码、KV Cache 和部署方案，避免把应用侧的并发数据说成模型推理性能。

## Agent 专题补充

- **混合路由与权限**。证据核验模式中，固定意图先走规则，其他请求由模型或离线路由处理。模型路由报错只允许只读检索。所有计算先暂停确认，恢复后才写入队列。可在 `tests/test_harness.py` 看到拒绝审批和路由故障均未生成任务的断言。[混合路由](https://notes.kamacoder.com/interview/llm/agent_hybrid_routing_interview.html) · [生产 Agent](https://notes.kamacoder.com/interview/llm/production_agent_architecture_harness_org_talent.html)
- **Loop、图编排和预算**。`workflow.py` 通过 LangGraph 条件边实现检索、证据选句、校验和补检索，最多检索两次，每次最多三段、每段最多 450 字符。首次混合召回，补检索用 BM25，只把未用的来源交给选句节点。每次模型选句最多输出 384 tokens。路由预算另计。审批与工具重试沿用原有检查点和 SQLite 租约机制。[Loop Engineering](https://notes.kamacoder.com/interview/llm/loop_engineering_interview.html) · [上游 LangGraph 控制流文档](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- **幻觉控制的边界**。核验器要求每行是所引证据里的原文，且每个引用必须实际对应某行。正确的引用 ID 搭配编造内容也会被拒绝。回归用例覆盖换源后通过、没有来源时拒答。原文校验只验证它确实出现过，来源真假、语义相关性和相互冲突仍需额外治理。[上下文漂移](https://notes.kamacoder.com/interview/llm/agent_drift_hallucination_interview.html) · [幻觉控制](https://notes.kamacoder.com/interview/llm/agent_hallucination_control_interview.html)
- **可观测与回放**。运行 API 的 `audit` 汇总路由、检索轮次、草稿次数、核验结果、成功返回的模型用量。未回传的用量保留为空。节点轨迹保留检索策略、证据 ID、耗时和失败类别。使用 `uv run --locked pytest -q tests/test_harness.py` 可重放固定输入和故障注入。[Harness 可观测性](https://notes.kamacoder.com/interview/llm/agent_harness_observability_interview.html)
- **待扩展的考点**。当前 Planner、选句和 Reviewer 分工由一张图串起来。独立多 Agent、跨会话记忆、可版本化 Skill 分发、分布式追踪和真实供应商成本对比仍只在面试笔记中讨论。[多 Agent 编排](https://notes.kamacoder.com/interview/llm/multi_agent_communication_interview.html) · [Multi-Agent Harness](https://notes.kamacoder.com/interview/llm/multi_agent_harness_interview.html) · [Agent 题目总览](https://notes.kamacoder.com/interview/llm/#agent-%E6%99%BA%E8%83%BD%E4%BD%93%E7%AF%87)

铝样例可以用来说明模型和计算工具的职责。Agent 只选择动作和参数，后端校验并等待审批。ASE 用 EMT 求势能和受力，用 BFGS 更新坐标，回归测试核对能量下降、最大力达到阈值以及导出的周期结构可读。工作流可以在离线路由下复现。

来源：[训练全流程](https://notes.kamacoder.com/llm/intro/how_llm_trained.html) · [SFT、RLHF、DPO](https://notes.kamacoder.com/llm/app/finetuning_sft_rlhf_dpo.html) · [LoRA/QLoRA](https://notes.kamacoder.com/llm/app/lora_qlora.html) · [QKV](https://notes.kamacoder.com/llm/transformer/qkv.html) · [部署选型](https://notes.kamacoder.com/llm/app/deployment_options.html)

## 复习顺序

先跑一次带引用问答，一次先查后审再计算，以及一次超时重试。再看逐题评测报告，找出单路召回漏掉的英文问题。最后读公开面经中对应的追问。这个顺序能把自己实际跑过的行为和知识点放在一起讲。

入口：[主学习路线](https://notes.kamacoder.com/llm/intro/llm_learning_roadmap.html) · [Agent 专项路线](https://notes.kamacoder.com/llm/app/agent_learning_roadmap.html) · [面经目录](https://notes.kamacoder.com/interview/llm/) · [字节 Agent 面经](https://notes.kamacoder.com/interview/llm/#真实面经) · [小红书观测与评测面经](https://notes.kamacoder.com/interview/llm/company/20261012xiaohongshu_ai_engineer_interview.html)

## 面试题库与追问

### 一、项目介绍与个人贡献

1. **用 90 秒讲清楚这个项目解决什么问题。** 从材料资料核验和计算执行讲起，串起检索、审批、任务队列和 ASE 结果。最后用一条可演示的结果收尾。追问通常落在为什么要用模型、哪些步骤只靠规则即可。

   **项目口述**　我的项目是一个材料计算 Agent，面向两个连续动作：先查清材料依据，再把计算提交给后台。我用硅的晶体结构问答演示证据怎么进回答，用「先查铝的资料，再提交几何优化」演示审批和执行。后台把任务状态和产物保留下来，用户能回看轨迹和下载结构。模型负责有限的意图判断和证据选取，队列、审批和数值计算都由程序执行。
2. **哪些是你能讲透的实现，哪些直接使用上游？** 按函数和职责讲清 LangGraph 的检查点、ASE 的计算、3Dmol.js 的渲染，以及仓库里的审批、证据核验、任务持久化和前后端集成。准备打开一段代码解释输入、边界和测试。个人贡献按自己实际承担的工作表述。

   **项目口述**　这套项目用 LangGraph 做图和检查点，ASE 执行数值计算，3Dmol.js 渲染结构。我重点讲仓库里怎样把它们接起来，比如 `workflow.py` 的审批和路由，`harness.py` 的引用核验，以及 `tasks.py` 的租约和去重。我可以现场从一次请求跟到任务记录，再打开相应测试。
3. **给一个真实的失败案例，从输入追到修复。** 可以回放合法引用 ID 搭配编造结论的回归用例。说明原来哪道校验漏过它、现在怎么检查、换源什么时候有用，以及如何防止同样的问题回归。

   **项目口述**　我会讲『引用 ID 合法，结论却是编的』。模拟模型返回一个真实候选的 ID，但把硅说成面心立方金属。核验器逐行检查所引原文，第一轮返回 `unverified_excerpt`，第二轮换检索策略只看新证据。回归测试验证最终返回的是新证据的原文，错误句没有出现在结果里。
4. **真实计算的结果如何证明？** 用铜或镍的 XYZ 跑一次固定晶胞优化，展示逐步最大力、收敛阈值和前后 extxyz。追问包括为什么能量可能为负、判断收敛看什么、经验势的适用范围是什么。用 `tests/test_structure_lab.py` 的数值断言支撑。

   **项目口述**　我用四原子的铜晶胞做固定晶胞优化。ASE 的 EMT 势计算能量和力，BFGS 更新坐标。一次真实运行里，最大力从 1.1114 降到 0.0107 eV/Å，低于 0.03 eV/Å 的阈值，共 6 步。我会展示前后结构和逐步 CSV。单次能量的正负依赖经验势的参考基准，收敛看设定的力阈值。
5. **只留一项最有说服力的工程指标，你选什么？** 可以选回归集内的证据核验、任务失败恢复或检索评估。回答时同时给题集、对照组和适用范围，准备解释指标异常如何定位。

   **项目口述**　我会讲同一题集下的检索对照。12 道可答题、2 道无关题，BM25 的 Recall@3 和 MRR 都是 0.5833，融合两路之后都是 1.0000，两道无关题两种策略都返回空候选。这是小样本同域结果，有些短语参与过调试。我会拿逐题报告说明漏召回的位置，线上泛化要另做留出集。

面经线索来自字节的项目连续追问和美团对验收、稳定性与指标归因的追问。[字节 Agent 四面](https://notes.kamacoder.com/interview/llm/#真实面经) · [美团 Agent 秋招](https://notes.kamacoder.com/interview/llm/company/20261015meituan_agent_campus_interview.html)

### 二、意图路由、Agent Loop 与图编排

6. **为什么这里用 LangGraph？Agent、Workflow 和 ReAct 有什么区别？** 用一条「先查再算」请求画出路由、检索、审批和入队。固定依赖在图里，模型负责有限决策，ReAct 适合需要根据工具反馈动态选择下一步的任务。

   **项目口述**　拿「查铝再优化」举例，先确定动作和参数，检索后暂停等审批，批准才入队。LangGraph 把这些分支和恢复点显式定义出来。资料问答可以根据核验结果补检索一次。用 ReAct 会更适合下一步未知、工具反馈会改变计划的任务，这个项目的写入路径依赖固定，我保留了显式状态。
7. **规则路由和模型路由怎么分工？如何评估？** 核验模式对少数固定输入精确匹配，其余由 Planner 判断。设计评测时加错别字、否定句、读写混合请求和边界同义句，分别看写入误触发率、规则覆盖率和模型调用比例。

   **项目口述**　证据核验模式里，像「硅的晶体结构是什么」这类少量固定问法直接命中规则，其他问题交给 Planner。轨迹能看到有没有走到模型。若做路由评估，我会把口语改写、否定句、读写混合分开测，写操作误触发单独统计，因为查询错分和实际提交的代价不同。
8. **模型不可用时怎样降级，怎么防止降级后误提交？** 核验模式将模型路由失败转成只读查询。正常写入仍要用户确认。追问模型能否通过其他入口绕过审批时，区分研究 Agent、只读 MCP 和实验室显式提交。

   **项目口述**　Planner 抛出失败时，核验模式只把离线判断用来提取材料，然后固定进入只读查询。通过模型正常判定为计算的请求也要走审批。测试里我用「提交铝的能量计算」触发失败，最后检查 SQLite 任务表仍为空；只读 MCP 本身也没有提交工具。
9. **什么时候停止重检索？为什么改走 BM25？** 首轮混合检索，核验未通过时再尝试一次 BM25，剔除已经选过的证据。第二轮没有新证据时跳过选句。追问增加轮次的收益时，比较恢复率、拒答率、P95 和多消耗的调用量。

   **项目口述**　我限制最多两次检索。首轮用混合检索；核验没通过时第二轮用 BM25，只保留未见过的片段。如果第二轮没有新片段，直接跳过再次选句，结束时拒答。补检索的测试构造了旧片段和新片段，能验证旧片段不会被再次交给选句节点。
10. **怎么设计 Planner、Worker、Reviewer 之间的依赖？** 现有图分开路由、选句和验证，后台 Worker 执行纯计算。设计题给出可以并行的独立子任务、结构化交接字段、归并规则、单分支超时和局部重试。

   **项目口述**　当前分工是 Planner 负责决定动作，选句节点选证据，Reviewer 用程序匹配原文。后台的 Worker 处理已经获批的计算。假如要同时查多种材料，我会给每个并行分支固定材料和返回 Schema，然后在汇总节点统一核验。现在用一张 LangGraph 图就能跑完整流程。
11. **工作流中断后恢复到哪一步？如何防止重复执行？** 区分 LangGraph 的等待状态和后台 SQLite 的任务状态。画出审批等待、重启加载、恢复并入队的时序，再指出提交节点需要自己的幂等约束。

   **项目口述**　用户补参数或确认审批时，LangGraph 把等待点存到 SQLite 检查点，重启后按原运行 ID 找回来。后台任务有自己的状态表。即使任务已经写入而检查点还没保存，重放提交节点也会按运行 ID 找到原任务，不会再入队一条。
12. **什么时候值得做多 Agent？怎样控制子 Agent 的上下文和权限？** 设计题。以多材料独立调查为例，比较单流程多工具和多个独立执行单元，定义每个任务的输入、产物、预算及允许工具，再用成功率、耗时和成本判断收益。

   **项目口述**　如果任务是同时调研几种材料，各分支有不同资料范围或工具权限，才有理由试独立子 Agent。我会先把现有单图做成并行分支的基线，再比较一次完成率、P95 和用量。各子任务只接收材料、目标和允许工具，返回带来源的结构化结果。当前实现是单图和后台计算进程。

面经线索来自字节实习一面的 DAG 和记忆、理想应用研发的路由，以及美团对 Agent Teams 取舍的追问。[实习面经入口](https://notes.kamacoder.com/interview/llm/#真实面经) · [理想应用研发](https://notes.kamacoder.com/interview/llm/company/20261010lixiang_intelligent_application_interview.html) · [图编排](https://notes.kamacoder.com/interview/llm/graph_engineering_interview.html)

### 三、Function Calling、MCP 与工具治理

13. **Function Calling 的完整执行流程是什么？** 讲清后端发送工具 Schema、模型给出工具名和参数、应用解析校验，再由业务代码执行。用 `planner.py` 举例，追问为何工具名正确、参数类型正确仍可能触发错误业务动作。

   **项目口述**　以 `plan_materials_request` 为例，后端把工具 Schema 连同上下文发给模型；模型返回工具名和 JSON 参数；适配器核对工具名、调用数量，再用 Pydantic 校验参数。返回的只是路由决策，实际查询和计算入队由图节点执行，写操作还要审批。
14. **MCP 解决什么问题？项目为什么用 stdio？** 区分模型工具意图和 MCP 客户端与服务端的工具发现、调用。项目用 SDK 运行本地子进程，测试通过真实 stdio 会话列出并调用只读工具。追问远程传输、身份认证与访问控制属于设计题。

   **项目口述**　项目里 Function Calling 解决模型怎样表达结构化决定。MCP 用来让外部客户端发现并调用检索、任务查询两个工具。本地用 stdio 启动服务，集成测试实际建会话、列工具并调用。假如要远程提供，我会另设计传输、认证和工具授权。
15. **新工具该如何设计 Schema、错误码和返回值？** 以提交计算为例，写清枚举、必填字段、单位和参数缺失时的行为。区分参数错误、暂时不可用及业务拒绝，分别决定澄清、重试或终止。

   **项目口述**　以提交任务为例，材料、计算类型和计算后端有固定参数范围，缺失字段先暂停补全。非法参数应当在入队前拒绝；工具超时可以在预算内重试；本地执行异常有失败事件。结果里区分任务 ID、状态和计算产物，前端能按同一 ID 轮询或订阅。
16. **工具、Skill、MCP、记忆各负责什么？** 用「做一次材料查证」举例。工具执行操作，MCP 提供工具接入，Skill 封装流程和验收标准，记忆保存可跨任务使用的信息。设计题追问 Skill 如何按需选择、固定版本、灰度和做回归。

   **项目口述**　拿『查铝再计算』举例，检索和计算是具体工具，MCP 是只读工具的接入协议，运行中的参数和证据是检查点状态。如果把操作步骤、边界和验收标准封装成可选择的 Skill，我会记录版本并配回归用例。项目目前把可复用步骤写在图里。
17. **检索到的文档夹带指令，系统靠什么控制工具？** 展示材料证据的选句节点只能输出答案结构，队列写入由单独路径和人工确认控制。设计题讨论工具权限和知识源权限，准备解释合法原文仍可能过时或包含不可信内容。

   **项目口述**　项目里文档作为证据输入，选句阶段只允许输出答案和引用。真正的写入在独立的计算分支，仍需要用户确认。即使模型照搬了一段带指令的原文，选句工具也没有入队能力。原文通过核验之后，还需要用来源权限和可信度判断这段资料应不应该展示。

面经线索来自字节的工具与 MCP、快手的接入方式选择以及美团的工具说明和调用顺序。[字节 Agent 四面](https://notes.kamacoder.com/interview/llm/#真实面经) · [快手 Agent](https://notes.kamacoder.com/interview/llm/company/20260928kuaishou_agent_interview.html) · [Agent Skill 专题](https://notes.kamacoder.com/interview/llm/agent_skill_interview.html)

### 四、RAG、引用与上下文

18. **从 Markdown 文件到可追溯答案经过哪些步骤？** 依次讲按标题切片、重叠窗口、索引构建、材料过滤、召回和引用校验。追问为什么按标题切，以及切片太短或太长分别损失什么。

   **项目口述**　我把 Markdown 按标题分段，长段按 450 字符切片，重叠 60 字符，并保留文件名和标题。查询时先约束材料范围，再从关键词和字符特征两路召回。以『硅的晶体结构』为例，最后能够定位到硅的结构资料，并校验答案是否确实摘自它。
19. **BM25、字符 n-gram、Embedding 分别解决什么问题？** 举元素缩写、中文短词、同义问法三个例子。当前两路都是稀疏字面特征，向量语义召回和 ANN 作为设计题讨论，比较内存、更新和查询成本。

   **项目口述**　BM25 对 Fe、FCC 这种精确术语有用；字符 n-gram 适合中文短串和词形重合的问法。当前把这两路合并，避免一种字面匹配的盲区。Embedding 可以补充表述差异较大的问法。接向量索引前，我会先在独立同义改写集上看 Recall@3 和新增延迟。
20. **混合排序为什么用 RRF？什么时候加 Rerank？** 解释不同召回器的原始分数尺度不同，RRF 用排名融合，之后叠加领域短语权重。追问怎样用消融实验区分融合、短语规则和二阶段精排的影响。

   **项目口述**　BM25 和字符余弦的原始分值不好直接相加，所以我先按各自排名做 RRF，再加领域短语权重。想证明收益，可以固定语料和题集，分别跑单路、融合、融合加短语三个设置。再考虑用候选后的 Reranker 修排序，并看延迟是否值得。
21. **有正确的文档但答案不对，怎么定位到哪一层？** 依次看文件是否入库、预期片段是否出现、排序是否截断、模型是否引用以及原文是否支持。分别给召回、排序、生成和校验设指标。

   **项目口述**　我先看检索节点记录的候选 ID。预期 ID 没出现，就检查导入和召回；出现但排在候选上限之外，就看排序；已经给到模型却没被使用，就看选句和引用。正确引用配错误陈述时，核验会打出 `unverified_excerpt`，可以直接归到生成阶段。
22. **怎样降低带引用的幻觉？核验通过意味着什么？** 先查引用是否属于候选，再要求回答的每行出现在所引原文中。准备回答相关性、来源版本、事实准确性与冲突证据如何另行核实。

   **项目口述**　项目先确认引用 ID 属于本次候选，再逐行匹配所引片段。这样能发现『引用没错，描述却编了』。这个校验只证明模型摘到了原文，原文相关性、资料版本、不同来源冲突仍需要另外处理。
23. **如何让短查询和跨文档问题答得更好？** 设计题。分别讨论领域同义词、Query 改写、父子索引与多步检索，比较改写引入意图漂移和展开上下文的成本。用现有两轮有限检索作为起点。

   **项目口述**　如果用户只说『力阈值』，我先用现有领域短语和混合召回作基线。对于必须结合多段资料的问题，可以按需要回取父段，或拆成两条查询再合证据。我会同时记录查全率和错误改写比例，保留原问题作核验，避免查询改写把对象换成另一种材料。
24. **上下文预算怎么管？短期状态和长期记忆怎么分？** 当前核验最多每轮三段、每段 450 字符，运行状态在检查点。设计题讨论按任务摘要、跨会话记忆的写入条件、来源和过期策略。说明字符预算和实际 Token 用量的区别。

   **项目口述**　选句节点每轮最多接收三段，每段最多 450 字符，最多两轮。待审批和当前选中的证据是运行状态，留在检查点。持久的材料资料在检索索引里。跨会话偏好如果要做，我会单独管理写入许可、来源和过期策略。实际 Token 以模型回传为准。
25. **资料更新或删除后，怎样知道旧回答用了什么？** 设计题。给文档、切片和索引引入版本，区分历史审计与当前查询可见范围，验证旧版本退出召回。结合本项目资料启动时建索引的方式说明变更成本。

   **项目口述**　现在资料在启动时构建索引，历史运行保留当时取到的证据。要支持持续更新，我会给源文档和切片保存稳定 ID 与版本，把历史审计快照和当前索引分开。测试既要确认旧版本不会再出现在新查询，也要能解释旧回答依据的版本。

面经线索来自番茄实习对混合检索与上下文的追问，以及千问、美团日常实习对权限、切片、短 Query 和证据失效的追问。[实习面经入口](https://notes.kamacoder.com/interview/llm/#真实面经) · [RAG 评估](https://notes.kamacoder.com/llm/app/rag_evaluation.html) · [幻觉控制](https://notes.kamacoder.com/interview/llm/agent_hallucination_control_interview.html)

### 五、可靠性、压测与可观测性

26. **同一请求发两次会生成几个任务？** 画出 API 的 Idempotency-Key、运行 ID 和任务表唯一约束。追问同一个键搭配不同请求，以及任务写入后检查点未提交两个场景，准备打开对应回归测试。

   **项目口述**　客户端用同一个 Idempotency-Key 重发同一内容，API 返回同一个运行；换内容会冲突。任务表按运行 ID 唯一，因此提交节点重放也复用同一任务。测试专门模拟了任务先落库、检查点晚一步失败的顺序。
27. **Worker 算到一半退出，怎么恢复？如何处理旧结果？** 讲清租约过期才允许重领，新的领取会换令牌，落库时核验当前令牌。纯计算可能再次执行，带外部副作用的工具还需要业务幂等。

   **项目口述**　Worker 领取时会拿到租约和唯一令牌。旧进程断掉，租约过期后可重新领取，领取令牌随之更换。结果落库时必须匹配当前令牌，旧结果来晚了会被拒绝。计算本身可能执行两次，有副作用的操作需要业务层另做幂等。
28. **超时怎么设？什么时候重试，什么时候直接失败？** 区分请求、工具子进程和任务租约三个边界。展示首次超时可恢复和持续超时达到上限的测试。设计题延伸到退避、抖动、负载高时的保护和慢任务队列。

   **项目口述**　项目的 ASE 计算在独立子进程里，有 25 秒超时；任务租约至少 35 秒。超时最多允许再尝试一次，已确认的本地执行错误直接失败。模拟后端能稳定复现一次超时后成功和两次超时后失败。生产值我会按任务耗时分布再定。
29. **SSE 断线后怎样补读？事件会重复或失序吗？** 客户端带游标，服务端按事件 ID 查询并分页。追问终态何时发送、页面怎么去重和轮询兜底，以及多实例时用什么共享事件源。

   **项目口述**　任务事件先持久化，再由 SSE 推送。断线后客户端带最后收到的 ID，服务端查比它更新的事件，按 ID 分页；发完积压再发送终态。前端多次断线会回退到轮询。这部分可用 `tests/test_interview_features.py` 的多页补读测试证明。
30. **给你一条失败运行，怎么用 Trace 找出问题？** 先用运行 ID 定位路由、证据和审批，再用任务 ID 对照领取与失败事件。区分可观测记录、模型用量缺失及敏感信息脱敏，说明哪些数据该进入评测回放。

   **项目口述**　一次失败我先从运行 ID 看路由、候选、核验结果和审批，再从任务 ID 看领取、超时或结束事件。比如核验失败先判断有没有候选，再看引用合法性和原文匹配。模型用量缺失就保留为空；线上需要把敏感内容和可用于回放的结构化事件区分开。
31. **如何设计离线评测集和上线回归？** 同时收录可答、拒答、越界、伪造引用、用户拒绝审批和重复提交。分别对结果正确性和轨迹约束打分，再通过独立留出的题集检查短语规则是否过拟合。

   **项目口述**　我会把评测分成结果和轨迹两层。结果层看可回答问题的召回、拒答、引用和计算不变量；轨迹层看最多两轮、拒绝审批零任务、重放无重复。现有固定 RAG 题和故障测试能作回归；独立留出集才用来评估泛化。
32. **怎么测 QPS、P95、SLO 内吞吐和成本？** 解释请求共用同一统计窗口，SLO 内吞吐只数达标请求。区分单接口、完整 Agent 流程和模型流式传输。项目的本机 40 次检索请求适合作为测量演示。

   **项目口述**　我先按接口分开测，当前压测脚本测的是本地检索 API。P95 看请求延迟分布，达标吞吐用同一时间窗口内满足 SLO 的请求数计算。完整 Agent 要分开记录模型调用、检索和后台排队，否则不能从单接口数据推算整条链路。
33. **如果要把单机版扩成多实例，先动哪里？** 设计题。先说明 SQLite 写竞争、进程内锁和本地 Worker 的边界。再说明共享状态库、消息队列、任务去重、背压与可观测性如何衔接，并考虑迁移中已有任务的恢复。

   **项目口述**　单机版的瓶颈候选是 SQLite 写竞争和进程内锁。我会先用并发写和长任务压测定位，再考虑共享数据库、独立 Worker 与队列。迁移时仍保留稳定任务 ID、幂等和旧领取令牌失效的规则，避免扩容的时候引入重复计算。

面经线索来自小红书的轨迹与回放、快手的指标和压测，以及美团的故障归因。[小红书 AI 研发](https://notes.kamacoder.com/interview/llm/company/20261012xiaohongshu_ai_engineer_interview.html) · [快手 Agent](https://notes.kamacoder.com/interview/llm/company/20260928kuaishou_agent_interview.html) · [美团 Agent 秋招](https://notes.kamacoder.com/interview/llm/company/20261015meituan_agent_campus_interview.html)

### 六、模型基础、推理与训练

34. **Prompt、结构化输出、Context Engineering 分别改哪一层？** 用路由举例，Prompt 描述意图，Schema 限制返回形状，Context Engineering 控制发送哪些资料、历史和工具说明。再解释为什么业务程序仍要验证参数。

   **项目口述**　拿路由器来说，Prompt 写明什么时候查询、什么时候计算；Schema 定义允许的动作和参数；上下文控制向模型发送哪些证据和问题。代码还要校验返回值，并决定实际工具权限与审批。这样能一层层定位是模型理解、输出形状还是业务权限的问题。
35. **Q、K、V 在注意力里各起什么作用？** 能写出缩放点积注意力并解释查询与键如何算权重、值如何加权汇总。追问自回归掩码、序列增长时注意力开销怎么变化。

   **项目口述**　原理上，Q 和 K 的点积经缩放和 softmax 变成权重，再对 V 加权求和，自回归掩码限制看未来位置。回到我的项目，长证据会推高模型输入长度，所以核验模式按片段数和字符数限制上下文。注意力和算子是推理服务内部机制，我这里用的是接口适配。
36. **Prefill、Decode、KV Cache、TTFT 和 TPOT 的关系是什么？** Prefill 处理输入并建立缓存，Decode 逐步生成。对比长输入、长输出、多个并发请求各自的开销。当前项目 SSE 传送后台任务事件，模型推理指标需独立测量。

   **项目口述**　Prefill 处理初始提示并建立 KV Cache，Decode 逐个生成 Token 并复用缓存。输入长常影响首 Token，输出长增加生成步数。我们工作台的 SSE 是任务事件，模型适配器返回结构化结果；如果接流式模型，我会单独记录首次输出和后续 Token 间隔。
37. **模型计费怎么估？怎样用预算限制 Agent 的成本？** 分开输入和输出 Token、模型单价与实际调用次数。用项目的输出上限和原文字符上限说明控制手段。真实供应商尚未联调，估值和回传计量分别记录。

   **项目口述**　我会按模型、输入输出 Token 和调用次数估算成本。项目里固定意图能少一次模型路由，核验最多两轮，模型选句每次输出上限是 384 Token。供应商回传用量才作为实际计量；本地离线演练不能当作线上账单数据。
38. **什么时候直接用 Prompt，什么时候做 RAG 或 SFT？** 判断问题来自知识缺口、提示和工具策略，还是跨任务的行为偏差。设计题用同一批留出数据比较正确率、幻觉、延迟和维护成本，再决定是否训练。

   **项目口述**　我的项目需要查材料事实和保留出处，所以用了 RAG；稳定工具结构靠 Schema 和程序校验。若问题是提示没说清楚，先改 Prompt；有标注证据表明跨任务的行为偏差在改提示、工具策略后还很稳定，才考虑 SFT，并在同一留出集上比效果和成本。
39. **LoRA、QLoRA、SFT、DPO、RLHF 怎么区分？** 先分清参数适配方法、监督训练目标和偏好对齐方法。准备回答数据长什么样、训练产物是什么，以及基线和回归集如何构造。

   **项目口述**　这套材料 Agent 使用现成模型接口，实验室跑的是 ASE 经验势计算。SFT 用示范输入输出做监督训练；LoRA/QLoRA 管参数适配和显存成本；DPO、RLHF 对应偏好对齐方法。如果未来要训练，我先写出数据来源、样本格式、对照组和回归标准。
40. **怎样把项目接到实际模型端点，并验证接入有效？** 从路由 Schema 兼容、超时与错误处理开始，再跑回答引用和审批的对照用例。对比离线、模拟端点和真实供应商的验证层级，分别记录结果、用量及延迟。

   **项目口述**　项目里已经有 Chat Completions 适配器和模拟端点测试。选定真实供应商后，我会先验证工具调用 Schema 和异常响应，再用同一组查询验证引用、拒答和审批行为，分开记录成功率、耗时和回传用量。这样能明确哪些是离线结果，哪些来自真实服务。

复习范围参考学习路线的模型调用、RAG、Agent、Transformer 与微调章节。模型基础另结合字节和快手面经复习。[昨天的大模型学习路线](https://notes.kamacoder.com/llm/intro/llm_learning_roadmap.html) · [大模型面经总览](https://notes.kamacoder.com/interview/llm/) · [快手 Agent](https://notes.kamacoder.com/interview/llm/company/20260928kuaishou_agent_interview.html)

### 现场手写与后端加练

- **最长公共子序列、最小覆盖子串。** 前者练状态定义、转移及二维到一维的空间压缩，后者练窗口计数、何时收缩，以及重复字符和空答案。分别来自小红书和快手的公开面经。[小红书 AI 研发](https://notes.kamacoder.com/interview/llm/company/20261012xiaohongshu_ai_engineer_interview.html) · [快手 Agent](https://notes.kamacoder.com/interview/llm/company/20260928kuaishou_agent_interview.html)
- **手写一个 DAG 调度器。** 这是根据项目改编的练习。输入有向边，输出可执行顺序，识别有环输入。加练只调度依赖已完成的节点，以及如何记录失败分支。
- **Redis 锁和索引。** 练锁的限时、持有者身份与原子释放，以及 MySQL 复合索引的最左前缀和失效场景。结合项目当前的 SQLite 写事务、租约令牌和事件索引解释不同层次的问题。[小红书 AI 研发](https://notes.kamacoder.com/interview/llm/company/20261012xiaohongshu_ai_engineer_interview.html)

先练项目题 1–5，再沿一条真实执行链练第 7、9、13、21、26、27、30、31 题。投 Agent 应用岗接着练检索和工具治理，投 AI Infra 岗接着练 26–37 题。准备一份本地检索报告和一条能够当场复现的故障轨迹。
