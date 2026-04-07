# TaijiOS

An AI operating system framework for building self-improving, autonomous agent systems.

TaijiOS provides the core infrastructure for orchestrating AI agents, managing LLM routing, implementing self-healing pipelines, and enabling continuous learning from experience.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   TaijiOS Core                   │
├──────────┬──────────┬──────────┬────────────────┤
│ EventBus │Scheduler │ Reactor  │ Memory/Registry│
├──────────┴──────────┴──────────┴────────────────┤
│              LLM Gateway (port 9200)             │
│  auth ─ policy ─ routing ─ failover ─ audit      │
├─────────────────────────────────────────────────┤
│           Agent System Framework                 │
│  task_queue ─ executor ─ lifecycle ─ experience  │
├─────────────────────────────────────────────────┤
│          Self-Improving Loop                     │
│  feedback ─ evolution ─ policy_learner ─ rollback│
├─────────────────────────────────────────────────┤
│          GitHub Learning Pipeline                │
│  discover ─ analyze ─ digest ─ gate ─ solidify   │
└─────────────────────────────────────────────────┘
```

## Core Modules

- `aios/core/` — Event-driven engine, scheduler, reactor, memory, model router, circuit breaker, budget control, feedback loop, evolution scoring
- `aios/gateway/` — Unified LLM Gateway with authentication, rate limiting, provider failover, audit trail, and streaming support
- `aios/agent_system/` — Task queue with atomic transitions, agent lifecycle management, experience harvesting and learning
- `coherent_engine/core/` — Vision alignment engine for multi-shot coherence
- `self_improving_loop/` — Safe self-modification with rollback and threshold gates
- `github_learning/` — Learn from external GitHub projects: discover, analyze, digest, gate, solidify

## Quick Start

```bash
# Clone
git clone https://github.com/<your-org>/taijios.git
cd taijios

# Install dependencies
pip install -r requirements.txt

# Start the LLM Gateway
python -m aios.gateway --port 9200

# Run the GitHub learning pipeline
python -m github_learning discover --limit 5
python -m github_learning analyze
python -m github_learning digest
python -m github_learning gate list
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

## Design Principles

1. **Self-healing by default** — Validation failures trigger automatic retry with guidance injection
2. **Experience-driven** — Every execution produces experience data that improves future runs
3. **Gate everything** — External mechanisms pass through human review before entering mainline
4. **Evidence-first** — Every decision, failure, and recovery is logged with structured evidence
5. **Graceful degradation** — Components degrade to fallbacks, never crash the system

## License

MIT
