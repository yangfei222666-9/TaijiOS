# TaijiOS 太极OS

<p align="center">
  <strong>AI Operating System — 自进化、自愈、自学习的智能体操作系统框架</strong>
</p>

<p align="center">
  <a href="#architecture-架构">Architecture</a> ·
  <a href="#quick-start-快速开始">Quick Start</a> ·
  <a href="#modules-模块">Modules</a> ·
  <a href="#github-learning-pipeline-github学习管道">Learning Pipeline</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

TaijiOS is a framework for building AI systems that improve themselves through experience. It provides event-driven orchestration, unified LLM routing, self-healing pipelines, and a learning pipeline that absorbs knowledge from external GitHub projects.

太极OS 是一个让 AI 系统通过经验自我进化的框架。它提供事件驱动编排、统一 LLM 路由、自愈流水线，以及从外部 GitHub 项目吸收知识的学习管道。

> 核心理念：吸收别人的经验，消化别人的坑，沉淀成自己的机制。

## Architecture 架构

```
┌──────────────────────────────────────────────────────────┐
│                     TaijiOS Core 核心层                    │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────────┐  │
│  │ EventBus │ │Scheduler │ │Reactor │ │Memory/Registry│  │
│  │  事件总线  │ │  调度器   │ │ 反应器  │ │  记忆/注册表   │  │
│  └────┬─────┘ └────┬─────┘ └───┬────┘ └──────┬───────┘  │
│       └────────────┴───────────┴─────────────┘           │
├──────────────────────────────────────────────────────────┤
│                LLM Gateway 统一网关 (:9200)                │
│                                                          │
│  认证 ─── 策略 ─── 路由 ─── 故障转移 ─── 审计              │
│  auth     policy   routing   failover     audit          │
├──────────────────────────────────────────────────────────┤
│              Agent System 智能体框架                       │
│                                                          │
│  任务队列 ─── 执行器 ─── 生命周期 ─── 经验引擎              │
│  task_queue  executor  lifecycle   experience             │
├──────────────────────────────────────────────────────────┤
│              Self-Improving Loop 自进化环                  │
│                                                          │
│  反馈环 ─── 进化评分 ─── 策略学习 ─── 安全回滚              │
│  feedback   evolution   policy      rollback             │
├──────────────────────────────────────────────────────────┤
│              GitHub Learning 学习管道                      │
│                                                          │
│  发现 ──→ 分析 ──→ 提炼 ──→ 人工门控 ──→ 固化              │
│  discover  analyze  digest    gate       solidify         │
└──────────────────────────────────────────────────────────┘
```

## Modules 模块

| Module | Description | 说明 |
|--------|-------------|------|
| `aios/core/` | Event engine, scheduler, reactor, memory, model router, circuit breaker, budget, feedback loop, evolution | 事件引擎、调度器、反应器、记忆、模型路由、熔断器、预算、反馈环、进化评分 |
| `aios/gateway/` | Unified LLM Gateway — auth, rate limiting, provider failover, audit, streaming | 统一 LLM 网关 — 认证、限流、故障转移、审计、流式传输 |
| `aios/agent_system/` | Task queue (atomic transitions), agent lifecycle, experience harvesting | 任务队列（原子状态转换）、智能体生命周期、经验收割 |
| `coherent_engine/core/` | Vision alignment for multi-shot coherence | 多镜头视觉一致性对齐引擎 |
| `self_improving_loop/` | Safe self-modification with rollback and threshold gates | 安全自修改 + 回滚 + 阈值门控 |
| `github_learning/` | Learn from GitHub: discover, analyze, digest, gate, solidify | 从 GitHub 学习：发现、分析、提炼、门控、固化 |

## Quick Start 快速开始

```bash
# Clone
git clone https://github.com/yangfei222666-9/TaijiOS.git
cd TaijiOS

# Install
pip install -e .

# Start the LLM Gateway 启动网关
export TAIJIOS_GATEWAY_ENABLED=1
python -m aios.gateway --port 9200

# Run the GitHub Learning Pipeline 运行学习管道
export GITHUB_TOKEN=your-github-token
python -m github_learning discover --limit 10   # 发现项目
python -m github_learning analyze                # LLM 分析
python -m github_learning digest                 # 提炼机制
python -m github_learning gate list              # 查看待审
python -m github_learning gate approve <id>      # 人工批准
python -m github_learning solidify               # 固化为经验
```

## Configuration

All secrets and paths are configured via environment variables:

```bash
# LLM Gateway
export TAIJIOS_GATEWAY_ENABLED=1
export TAIJIOS_API_TOKEN=your-token

# GitHub Learning
export GITHUB_TOKEN=your-github-token

# Optional: Telegram notifications
export TAIJI_TELEGRAM_BOT_TOKEN=your-bot-token
export TAIJI_TELEGRAM_CHAT_ID=your-chat-id
```

## GitHub Learning Pipeline GitHub学习管道

TaijiOS doesn't just run agents — it learns from the open-source ecosystem and evolves.

太极OS 不只是运行智能体，它从开源生态中学习并进化。

```
GitHub ──→ Discover ──→ Analyze ──→ Digest ──→ Gate ──→ Solidify
           发现项目      4问分析      提炼机制    人工门控    固化经验
                           │
                    ┌──────┴──────┐
                    │ 4 Questions │
                    │ 总控四问      │
                    ├─────────────┤
                    │ 1. 根问题？   │
                    │ 2. 踩过的坑？ │
                    │ 3. 可迁机制？ │
                    │ 4. 如何门控？ │
                    └─────────────┘
```

The gate is always manual — auto-discovery feeds candidates, humans decide what enters TaijiOS.

门控永远是人工的 — 自动发现提供候选，人来决定什么进入太极OS。

## Design Principles 设计原则

| Principle | 原则 | Description |
| --------- | ---- | ----------- |
| Self-healing | 自愈优先 | Validation failures trigger automatic retry with guidance injection |
| Experience-driven | 经验驱动 | Every execution produces experience data that improves future runs |
| Gate everything | 门控一切 | External mechanisms pass through human review before entering mainline |
| Evidence-first | 证据先行 | Every decision, failure, and recovery is logged with structured evidence |
| Graceful degradation | 优雅降级 | Components degrade to fallbacks, never crash the system |

## License

MIT
