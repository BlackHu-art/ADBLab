# ADBLab 第一期：开源技能/Agent 项目评审与接入方案（v0.1）

更新时间：2026-07-25

目标：为 ADBLab 构建可复用的代码侧 agent 能力来源清单，并给出可落地的 PoC 路线。

## 一、评审标准（按权重）

1. 生态成熟度（星标、维护活跃、文档）
2. Python 可集成性（与现有 PySide6/Python 3.11 一致）
3. 工具/技能兼容性（是否容易落地到现有操作模型）
4. 风险与实现成本（学习曲线、依赖风险）

> 评分：高 / 中 / 低

## 二、候选项目（热门 + 可执行）

| 序号 | 仓库 | 关注度 | 技术方向 | 适配评估 | 可落地优先级 |
| --- | --- | --- | --- | --- | --- |
| 1 | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | 非常高 | LLM 应用/Agent 骨架 | 可作为最稳基础层，扩展性强 | P1 |
| 2 | [microsoft/autogen](https://github.com/microsoft/autogen) | 高 | 多智能体协作框架 | 功能完整，适合任务拆解/调度 | P1 |
| 3 | [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | 高 | 角色化协作编排 | 与“流程步骤化操作”天然契合 | P1 |
| 4 | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 中高 | 图化状态机式多步流程 | 适合复杂状态控制、回退与重试 | P2 |
| 5 | [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | 中高 | 轻量多智能体流程 | 上手快，适合先做小闭环 | P1 |
| 6 | [openai/swarm](https://github.com/openai/swarm) | 中 | 多代理实验框架 | 适合概念验证，不建议直接作为生产基础 | P2 |
| 7 | [all-hands-ai/openhands](https://github.com/all-hands-ai/openhands) | 高 | 自研代码执行型 agent | 适合借鉴执行器/任务回路设计 | P3 |
| 8 | [aider-ai/aider](https://github.com/aider-ai/aider) | 高 | AI 编程协助 | 可借鉴变更/补丁策略 | P3 |
| 9 | [swe-agent/swe-agent](https://github.com/swe-agent/swe-agent) | 中高 | 自动 issue 修复闭环 | 可借鉴问题定位-修复策略 | P3 |
| 10 | [mukul975/Anthropic-Cybersecurity-Skills](https://github.com/mukul975/Anthropic-Cybersecurity-Skills) | 中高 | Skill 目录/标准化能力 | 适合“技能化”参考与素材 | P2 |
| 11 | [agentskills/agentskills](https://github.com/agentskills/agentskills) | 中高 | Skill 规范与格式 | 适合统一能力定义 | P1 |
| 12 | [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 高 | Skill 集合（插件化） | 可用于快速引入技能清单 | P1 |
| 13 | [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | 高 | 工程化技能包 | 适合直接筛选可迁移项 | P2 |

> 备注：表中项目未细化到单个 commit 成本，仅用于第一轮评审筛选。

## 三、对 ADBLab 的可行性判断（先行原则）

- 优先从“**最小闭环**”开始：先不引入重型统一框架，先建设 `ADBLab Skill 执行适配层`。
- 先让现有的日志、设备、任务、关闭流程通过 `Skill-Adapter` 暴露统一接口。
- 再逐步接入 1~2 个候选框架做 POC，避免一次性大迁移。

## 四、执行方案（建议）

### 第 1 阶段（第 1 周）：标准化基础
- 产出 `docs/architecture/agent_contract.md`：定义统一技能调用契约
  - 输入/输出结构
  - 错误码与重试规则
  - 日志标记（DEBUG/ERROR）与会话标识
- 产出 `utils/agent_skill_gateway.py`（PoC）：
  - `run_skill(skill_name, payload, context)` 统一入口
  - 与现有线程/取消机制对齐（不阻塞 UI）

### 第 2 阶段（第 2~3 周）：最小 PoC
- 对标 `openai-agents-python` 或 `crewAI` 做 2 个 demo 技能：
1. 设备日志收集技能（可重放、可暂停）
2. APK/文件操作技能（受控读写 + 错误上报）
- 输出：可执行演示脚本 + 测试用例
- 验收指标：
  - 功能不影响主窗口关闭逻辑
  - 技能调用失败不会触发主界面异常退出
  - 日志仅在 compiler/内部调试界面输出

### 第 3 阶段（第 4~5 周）：接入集合化技能
- 建立 `skills_map` 清单，按功能分组（日志、文件、ADB、远程）
- 抽样验证 `agent-skills` 标准化语义可映射到内部能力
- 形成“可插拔 + 可回滚”策略

## 五、首轮建议清单（立即开始）

1. 先行评估：`agentskills/agentskills`、`ComposioHQ/awesome-claude-skills`（标准化层）
2. 并行试点：`crewAI` 与 `openai-agents-python`（轻量 + 角色化）
3. 观察窗口：先做最小日志/文件/ADB 三个技能，做出可回滚 PoC
