# 材料计算 Agent 面试笔记

阅读日期为 2026-11-24。问题来自卡码笔记的学习路线、专题和公开面经。下面的排序按 Agent 应用研发、AI 后端和 Agent 平台岗与本项目的匹配度。面经是定性样本，无法估计各问题出现的概率。

## 1. 检索为什么选中这个片段？

面试常从完整链路问起，再追问如何定位召回失败、切片断上下文以及回答没有使用证据的问题。

项目先按 Markdown 标题分段，再按重叠窗口切分长段。检索同时跑 BM25 和字符 n-gram 余弦匹配，用 Reciprocal Rank Fusion 合并名次，加领域短语重排并保留前三条。两套召回都弱时会过滤候选。没有候选时返回资料不足。真实模型模式校验引用 ID 是否属于本次候选，引用校验本身不能证明回答的每句话都有证据。

运行 `python -m materials_agent.evaluation --out var/retrieval-report.json` 查看逐题结果。本次固定题集有 12 道可答题和 2 道无关题。BM25 的 Recall@3 和 MRR@3 都是 0.6667，混合检索都是 1.0000，两种模式都拒答了 2 道无关题。题集与资料卡同域，其中若干短语用于调试规则，结果仅能说明当前小语料上的行为。字符 n-gram 是稀疏字面特征。语义 Embedding、ANN 向量库和交叉编码器精排可以用更大的独立集做下一轮对比。

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

铝样例可以用来说明模型和计算工具的职责。Agent 只选择动作和参数，后端校验并等待审批。ASE 用 EMT 求势能和受力，用 BFGS 更新坐标，回归测试核对能量下降、最大力达到阈值以及导出的周期结构可读。工作流可以在离线路由下复现。

来源：[训练全流程](https://notes.kamacoder.com/llm/intro/how_llm_trained.html) · [SFT、RLHF、DPO](https://notes.kamacoder.com/llm/app/finetuning_sft_rlhf_dpo.html) · [LoRA/QLoRA](https://notes.kamacoder.com/llm/app/lora_qlora.html) · [QKV](https://notes.kamacoder.com/llm/transformer/qkv.html) · [部署选型](https://notes.kamacoder.com/llm/app/deployment_options.html)

## 复习顺序

先跑一次带引用问答，一次先查后审再计算，以及一次超时重试。再看逐题评测报告，找出单路召回漏掉的英文问题。最后读公开面经中对应的追问。这个顺序能把自己实际跑过的行为和知识点放在一起讲。

入口：[主学习路线](https://notes.kamacoder.com/llm/intro/llm_learning_roadmap.html) · [Agent 专项路线](https://notes.kamacoder.com/llm/app/agent_learning_roadmap.html) · [面经目录](https://notes.kamacoder.com/interview/llm/) · [字节 Agent 面经](https://notes.kamacoder.com/interview/llm/20260506bytedance.html) · [小红书观测与评测面经](https://notes.kamacoder.com/interview/llm/company/20261012xiaohongshu_ai_engineer_interview.html)
