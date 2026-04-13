# taijios-soul

Give any AI product a soul.

```python
from taijios import Soul

soul = Soul(user_id="alice")
response = soul.chat("今天心情不好")
print(response.reply)
```

Five Generals + 4D Intent Mixing + 3-Layer Memory + Personality Evolution — all running automatically behind three lines of code.

## Install

```bash
pip install taijios-soul
```

With Claude API support:

```bash
pip install taijios-soul[claude]
```

## Quick Start

```python
from taijios import Soul

# Zero config — runs with local ollama or mock mode
soul = Soul(user_id="alice")

# Chat — full 10-step soul pipeline runs automatically
r = soul.chat("帮我看一个bug")
print(r.reply)         # Soul-driven response
print(r.intent)        # {work: 0.7, chat: 0.1, crisis: 0.0, learning: 0.2}
print(r.stage)         # 初见 → 眼熟 → 熟人 → 老友
print(r.generals)      # Five Generals council result

# With Claude API
soul = Soul(user_id="bob", api_key="sk-ant-...")
r = soul.chat("为什么Redis用单线程反而更快？")

# Feedback drives evolution
soul.feedback(positive=True)

# End session — triggers memory consolidation
soul.end_session()
```

## License

MIT
