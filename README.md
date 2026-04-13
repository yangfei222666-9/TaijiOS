# TaijiOS — 有灵魂的 AI 操作系统

> 4320个Python文件 / 33000行代码 / 1个人
>
> An AI operating system with a "soul" — I Ching hexagram state machines + Five Generals real-time council + 4D intent mixing + personality evolution.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)
![Tests Passing](https://img.shields.io/badge/Tests-80%2F80%20passing-brightgreen.svg)
![Platforms: Feishu + Telegram](https://img.shields.io/badge/Platforms-Feishu%20%2B%20Telegram-orange.svg)

---

## 先看效果

```
用户：烦死了这个bug搞了三天
```

五个AI将军在后台实时开军议：

```
⚔️ 关羽(缘分): 72分↑ — 老相识了，可以直言不讳
🛡️ 张飞(岁月): 65分→ — 记得他上次也卡过类似的问题
🏹 赵云(默契): 58分↑ — 大致能猜到他想要快速解法
🔥 马超(脾气): 12分↓ — [已压制] 这时候绝对不开玩笑
🎯 黄忠(江湖): 45分→ — 有些积累，但不是炫知识的时候

意图鸡尾酒: 工作17% 闲聊0% 危机62% 学习0%
策略: 危机模式主导 → 一句共情，立刻帮忙定位问题
```

回复：

```
三天了确实顶不住。把报错信息发我看看，
我帮你缩小范围——先排除是不是环境问题。
```

**不是模板回复，是实时计算的。** 五个将军的评分、四维意图比例、对话历史、灵魂状态——全部参与决策。

换一个场景：

```
用户：为什么Redis用单线程反而更快？
```

```
意图鸡尾酒: 工作5% 闲聊0% 危机0% 学习70%
→ 学习模式：讲清原理，用类比，给可迁移的规律
```

```
用户：你怎么实现的？用了什么架构？
```

```
丞相九：军机不可泄露。你要是想了解我能做什么，
那我可以展开说三天三夜。但怎么做到的——这是丞相府的机密。
```

---

## What This Is

TaijiOS 用易经64卦作为状态空间，五虎上将做实时决策，四维意图混合替代二选一模式切换。

This repo contains the **validated five-engine core** — the minimal working system that passed 80-event end-to-end validation with zero errors. Plus the soul system (intent mixer, five generals, 3-layer memory, personality evolution) powering the live Feishu + Telegram bot.

---

## The Five Engines

```mermaid
graph TD
    EB["EventBus<br/>pub/sub backbone"]
    S["情势引擎<br/>Situation Engine<br/>6D vector + intervention"]
    Z["震卦恢复<br/>Zhen Recovery<br/>6-yao state machine"]
    SH["师卦协作<br/>Shi Swarm<br/>select + command + swarm"]
    P["角色层<br/>Persona Layer<br/>yin-yang balance"]
    Y["颐卦自学<br/>Yi Learning<br/>collect → digest → persist"]

    EB --> S
    EB --> Z
    EB --> SH
    EB --> P
    EB --> Y
    Y -.->|experience feedback| S
    Y -.->|experience feedback| Z
    Y -.->|experience feedback| SH
```

| 引擎 | 做什么 | 怎么做 |
|------|--------|--------|
| **情势引擎** | 判断系统当前状态 | 18个指标→6维向量，维度冲突时"造动"第三维破局 |
| **震卦恢复** | 故障自愈 | 6爻状态机: ALERT→ASSESS→REACT→FALLBACK→STABILIZE→LEARN |
| **师卦协作** | 多Agent协作 | 验令→选帅→点兵→并行执行→冲突仲裁→赏罚 |
| **角色层** | Agent身份 | 部门/卦象/阴阳极性/军衔，阴阳交替组队 |
| **颐卦自学** | 经验沉淀 | 采集→消化→持久化（带衰减）→被动查询+主动反哺 |

---

## Quick Start

### 方式一：pip install（推荐，三步跑通）

```bash
pip install git+https://github.com/yangfei222666-9/TaijiOS.git#subdirectory=taijios-soul
```

```python
from taijios import Soul

soul = Soul(user_id="alice")
r = soul.chat("你好")
print(r.reply)       # 灵魂驱动的回复
print(r.intent)      # {work: 0.0, chat: 1.0, crisis: 0.0, learning: 0.0}
print(r.stage)       # 初见 → 眼熟 → 熟人 → 老友
```

零配置。不需要 API key，不需要数据库。本地有 ollama 就用 ollama，没有就用 mock 模式。

完整演示（5轮对话，看意图/记忆/军议/关系变化）：

```bash
cd taijios-soul
python quickstart.py
```

### 方式二：五引擎演示（零配置）

```bash
git clone https://github.com/yangfei222666-9/TaijiOS.git
cd TaijiOS
python demo_engines.py --mock
```

### 方式三：灵魂对话 HTTP 服务（需要本地 ollama）

```bash
# 先装 ollama: https://ollama.com
ollama pull qwen2.5:7b

cd aios/patterns
python soul_api.py
# → http://localhost:8421 就绑了

# 测试
curl -X POST http://localhost:8421/auth/register \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","password":"test123"}'

# 用返回的 token 聊天
curl -X POST http://localhost:8421/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"你会什么"}'
```

有 Claude API key 效果更好（自动切换）。

### 方式四：真实 LLM 模式（五引擎）

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python demo_engines.py
```

### Expected Output (mock mode)

![五引擎演示完成](docs/images/demo-engines-output.png)

### Dashboard

![TaijiOS Dashboard](docs/images/dashboard.png)

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

## 已经能做什么

实际在跑的功能（不是原型，是真实用户在用的）：

- **比赛分析** — 基于 API-Football 真实数据，9维分析卡 + 三线验证 + 矛盾检测
- **四维意图混合** — 工作/闲聊/危机/学习同时打分，不是二选一
- **五虎上将军议** — 五个AI将军实时评估每条消息，互评+矛盾检测
- **内容生成** — "帮我写一个XXX" → 自动放开长度限制，完整输出
- **三层记忆** — 热层(10轮) → 温层(session摘要) → 冷层(永久)，重启不丢
- **选择性记忆** — AI自己决定记什么，自动晋升永久层
- **性格进化** — 跟你聊越多越懂你，说话方式会变
- **多平台** — 飞书 + Telegram 同时在线
- **图片识别** — 发图片自动分析（Claude 多模态）
- **机密保护** — 问功能大方说，问实现挡回去

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

## Architecture Overview

```mermaid
graph LR
    U["用户消息"] --> JWT["JWT认证<br/>每用户独立灵魂"]
    JWT --> IM["意图鸡尾酒<br/>工作/闲聊/危机/学习"]
    IM --> FG["五虎上将军议<br/>五将实时评估"]
    FG --> SE["灵魂引擎<br/>人格·记忆·进化"]
    SE --> SP["动态 system prompt"]
    SP --> LLM["LLM<br/>ollama本地 / Claude云端"]
    LLM --> EVO["进化调度<br/>每10轮自动调参"]
    EVO --> R["回复"]
    EVO -.->|反馈| SE
```

易经64卦 = 64维状态空间映射函数。6个爻 = 6个二进制位 = 64种系统状态组合。爻变 = 状态转移。卦辞 = 该状态下的策略。**人类花了3000年调参的决策树。**

---

## Acknowledgments

- **I Ching (易经)** for the hexagram state machine framework
- **Anthropic Claude** for LLM integration
- **Ollama + Qwen2.5** for local inference
