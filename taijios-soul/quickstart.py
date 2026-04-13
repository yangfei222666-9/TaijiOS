"""
TaijiOS Soul — 三步跑通

    python quickstart.py

零配置，不需要 API key，不需要 ollama。
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from taijios import Soul

# ── Step 1: 创建灵魂 ──
soul = Soul(user_id="quickstart_demo")
print(f"灵魂已创建 | 后端: {soul.backend} | 关系: {soul.stage}")
print()

# ── Step 2: 聊几轮，看系统怎么反应 ──
messages = [
    ("你好，我是新来的", None),
    ("帮我看一个Redis连接池的bug，超时报错", None),
    ("烦死了这个bug搞了三天", None),
    ("原来是配置文件编码问题，终于搞定了", None),
    ("为什么Redis用单线程反而更快？", None),
]

for msg, _ in messages:
    r = soul.chat(msg)
    print(f"[Round {r.interaction_count}] 你: {msg}")
    print(f"  意图: work={r.intent.get('work',0):.0%} chat={r.intent.get('chat',0):.0%} "
          f"crisis={r.intent.get('crisis',0):.0%} learning={r.intent.get('learning',0):.0%}")
    print(f"  关系: {r.stage} | 挫败度: {r.frustration}")
    print(f"  回复: {r.reply[:80]}{'...' if len(r.reply) > 80 else ''}")
    print()

# ── Step 3: 看看系统记住了什么 ──
print("=" * 50)
print("系统状态")
print("=" * 50)
print(f"关系阶段: {soul.stage}")
print(f"总交互数: {soul.interaction_count}")
print(f"LLM后端:  {soul.backend}")

# 检查记忆
mem = soul._memory.to_dict()
print(f"\n记忆: {mem['total']} 条 (永久: {mem['permanent']})")
if mem.get("by_category"):
    for cat, count in mem["by_category"].items():
        print(f"  {cat}: {count}")

# 检查军议
gen = soul._council.to_dict()
print(f"\n军议次数: {gen.get('total_councils', 0)}")
print(f"五将平均分: {gen['average_score']}")
for name, g in gen["generals"].items():
    print(f"  {name}({g['title']}): {g['score']}分 {g['trend']} — {g['opinion'][:30]}")

print(f"\n完成。灵魂数据保存在: ~/.taijios/quickstart_demo/")
