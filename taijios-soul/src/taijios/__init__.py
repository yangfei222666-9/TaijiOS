"""
TaijiOS Soul — 给任何 AI 产品装灵魂的中间件

三行接入:
    from taijios import Soul
    soul = Soul(user_id="alice")
    response = soul.chat("你好")
"""

from taijios.soul import Soul, SoulResponse

__version__ = "0.1.0"
__all__ = ["Soul", "SoulResponse"]
