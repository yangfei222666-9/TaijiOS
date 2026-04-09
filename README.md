# TaijiOS Five-Engine Core

**太极OS 五引擎内核**

> An evidence-driven AI operating system that applies I Ching hexagram mechanics to multi-agent coordination, fault recovery, and continuous learning.
>
> 以证据和门禁驱动的 AI 操作系统，将易经卦象机制应用于多智能体协作、故障恢复与持续学习。

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)
![Validation: 80/80](https://img.shields.io/badge/Validation-80%2F80%20events-brightgreen.svg)

---

## What This Is

TaijiOS uses I Ching hexagram state machines to govern five core engines for multi-agent systems. This repo contains the **validated five-engine core** -- the minimal working system that passed 80-event end-to-end validation with zero errors.

Not a framework. Not a wrapper. A working OS kernel for multi-agent systems, grounded in 3000-year-old decision theory, implemented in modern Python.

---

## The Five Engines

```
                    ┌─────────────────────────────────┐
                    │           EventBus               │
                    │       (pub/sub backbone)          │
                    └──┬───────┬───────┬───────┬───────┤
                       │       │       │       │       │
              ┌────────┴┐ ┌───┴─────┐ ┌┴──────┐ ┌────┴────┐ ┌────┴─────┐
              │Situation │ │  Zhen   │ │  Shi  │ │ Persona │ │    Yi    │
              │ Engine   │ │Recovery │ │ Swarm │ │  Layer  │ │ Learning │
              │ 情势引擎 │ │震卦恢复 │ │师卦协作│ │ 角色层  │ │ 颐卦自学 │
              │          │ │         │ │       │ │         │ │          │
              │ 6D vector│ │ 6-yao   │ │select │ │yin-yang │ │ collect  │
              │+intervene│ │ state   │ │command│ │ balance │ │ digest   │
              │          │ │ machine │ │+swarm │ │ +match  │ │ persist  │
              │          │ │         │ │       │ │         │ │ feedback │
              └──────────┘ └─────────┘ └───────┘ └─────────┘ └──────────┘
```

1. **Situation Engine (情势引擎)** -- Maps 18 system metrics to a 6-dimensional vector (timing, resource, initiative, position, relationship, energy). Detects tensions between dimensions and "intervenes" on a third dimension to break deadlocks, instead of forcing a direct tradeoff.

2. **Zhen Recovery Engine (震卦恢复引擎)** -- A 6-yao state machine (ALERT -> ASSESS -> REACT -> FALLBACK -> STABILIZE -> LEARN) for fault recovery. Balances yin force (Guardian Agent, defensive) and yang force (Reactor Agent, offensive) at each stage.

3. **Shi Swarm Engine (师卦协作引擎)** -- Multi-agent coordination following the "army hexagram" pattern: validate orders, select a commander, recruit a squad, execute in parallel, detect conflicts, arbitrate (vote/priority/merge), and apply rewards/punishments.

4. **Persona Layer (Persona 层)** -- Attaches rich identity to each agent: department, hexagram, yin/yang polarity, military rank, keyword activation rules. Selects balanced teams by alternating yin and yang members.

5. **Yi Learning Engine (颐卦自学引擎)** -- Collects experience records from the other four engines via EventBus, digests similar experiences into meta-lessons, persists with weight decay, and provides both passive query and active advisory feedback.

---

## Quick Start

### Mock Mode (zero configuration, no API key needed)

```bash
git clone https://github.com/YOUR_USERNAME/taijios.git
cd taijios
python demo_engines.py --mock
```

### Real LLM Mode

```bash
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json with your Anthropic API key, OR:
export ANTHROPIC_API_KEY=sk-ant-...
python demo_engines.py
```

### Expected Output (mock mode)

```
╔══════════════════════════════════════════════════════════╗
║          TaijiOS 五引擎全面演示                          ║
║                      模拟模式 (--mock)                     ║
╚══════════════════════════════════════════════════════════╝

  1. 情势引擎 — 六维向量 + 造动破解死锁
  2. 震卦恢复引擎 — 六爻状态机驱动故障恢复
  3. 师卦协作引擎 — 多 Agent 选帅/协作/仲裁/赏罚
  4. Persona 层 — 角色匹配 + 阴阳平衡
  5. 颐卦自学引擎 — 吸收/消化/沉淀/反哺
  6. 引擎注册中心 — 统一路由（五引擎）

EventBus 事件总数: 80
✅ 五引擎全面演示完成
```

---

## Validation Status

**Verified:**

- 80-event end-to-end demo, zero errors
- All five engines tested individually and in coordination
- EventBus routing across all engine types
- Mock mode fully functional without API dependency
- Yi learning engine collects 14 experience records, 3/3 queries hit

**In progress:**

- Production hardening (rate limiting, persistent storage backend)
- Larger sample validation beyond demo scenarios

**Not yet done:**

- Full test suite (unit tests, integration tests)
- Dashboard / monitoring UI
- SDK for external integration
- Multi-node deployment

---

## Design Philosophy

> 吸收别人的经验，消化别人的坑，沉淀成自己的机制。
>
> Absorb others' experience, digest their lessons, crystallize into your own mechanisms.

- **Evidence over claims** -- Every capability in this repo has been demonstrated end-to-end, not just designed on paper.
- **Auditable decision paths** -- Hexagram state machines provide deterministic, traceable flows. When fault recovery follows ALERT -> ASSESS -> REACT -> LEARN, you can trace exactly why each step was taken.
- **Intervention on the third dimension (造动)** -- When two system dimensions conflict, the situation engine does not force a tradeoff. It finds a third dimension to shift, breaking the deadlock without sacrificing either side.

---

## Project Structure

```
taijios/
├── demo_engines.py           # Full five-engine demo (entry point)
├── engine_registry.py        # Unified engine registry + event routing
├── event_bus.py              # EventBus pub/sub backbone
├── hexagram_lines.py         # Six-yao scoring (maps metrics to hexagram lines)
├── situation_engine.py       # Engine 1: 6D situation vector + intervention
├── zhen_recovery_engine.py   # Engine 2: 6-yao fault recovery state machine
├── shi_swarm_engine.py       # Engine 3: Multi-agent swarm coordination
├── agent_persona.py          # Engine 4: Agent identity + yin-yang balance
├── yi_learning_engine.py     # Engine 5: Self-learning experience loop
├── llm_caller.py             # Shared LLM caller (Anthropic Claude)
├── agents.json               # Agent definitions and metadata
├── config.example.json       # API key template
├── requirements.txt          # Python dependencies
└── LICENSE                   # MIT
```

---

## Configuration

Two ways to provide your Anthropic API key:

1. **Config file**: Copy `config.example.json` to `config.json` and replace the placeholder
2. **Environment variable**: `export ANTHROPIC_API_KEY=sk-ant-...`

`--mock` mode requires no key at all. All engines run with simulated LLM responses.

Each engine can also be run independently:

```bash
python situation_engine.py
python zhen_recovery_engine.py
python shi_swarm_engine.py
python agent_persona.py
python yi_learning_engine.py
python engine_registry.py
```

---

## License

MIT

---

## Acknowledgments

- **I Ching (易经)** for the hexagram state machine framework
- **Anthropic Claude** for LLM integration
