"""
taijios-soul 基础测试
运行: pytest tests/ -v
"""

import tempfile
import shutil
import os
import pytest

from taijios import Soul, SoulResponse


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="taijios_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_import():
    """包能正常导入"""
    import taijios
    assert taijios.__version__ == "0.1.0"
    assert hasattr(taijios, "Soul")
    assert hasattr(taijios, "SoulResponse")


def test_soul_init(tmp_dir):
    """零配置初始化"""
    soul = Soul(user_id="test_init", data_dir=tmp_dir)
    assert soul.stage == "初见"
    assert soul.interaction_count == 0
    assert soul.backend in ("claude", "ollama", "mock")


def test_soul_chat(tmp_dir):
    """chat 返回完整 SoulResponse"""
    soul = Soul(user_id="test_chat", data_dir=tmp_dir)
    r = soul.chat("你好")
    assert isinstance(r, SoulResponse)
    assert r.reply  # 非空回复
    assert r.stage  # 有阶段
    assert r.intent  # 有意图分析
    assert r.interaction_count == 1


def test_intent_detection(tmp_dir):
    """四维意图检测"""
    soul = Soul(user_id="test_intent", data_dir=tmp_dir)

    # 工作意图
    r = soul.chat("帮我看一个bug")
    assert r.intent.get("work", 0) > 0.3

    # 学习意图
    r2 = soul.chat("为什么Redis用单线程？")
    assert r2.intent.get("learning", 0) > 0.3


def test_generals(tmp_dir):
    """五将军军议"""
    soul = Soul(user_id="test_generals", data_dir=tmp_dir)
    r = soul.chat("你好")
    assert r.generals  # 有军议结果
    assert r.intent.get("lead_general")  # 有主将


def test_feedback(tmp_dir):
    """反馈闭环"""
    soul = Soul(user_id="test_fb", data_dir=tmp_dir)
    soul.chat("测试消息")
    soul.feedback(positive=True, detail="test")
    # 不崩就行——outcome 写入 JSONL
    outcomes_file = os.path.join(tmp_dir, "soul_outcomes.jsonl")
    assert os.path.exists(outcomes_file)


def test_end_session(tmp_dir):
    """会话结束"""
    soul = Soul(user_id="test_session", data_dir=tmp_dir)
    soul.chat("消息1")
    soul.chat("消息2")
    soul.end_session(summary="测试结束")
    # 不崩就行


def test_multi_round(tmp_dir):
    """多轮对话计数"""
    soul = Soul(user_id="test_multi", data_dir=tmp_dir)
    for i in range(3):
        soul.chat(f"第{i+1}轮")
    assert soul.interaction_count == 3


def test_persistence(tmp_dir):
    """重启后灵魂数据恢复"""
    soul1 = Soul(user_id="test_persist", data_dir=tmp_dir)
    soul1.chat("记住我")
    soul1.end_session()

    soul2 = Soul(user_id="test_persist", data_dir=tmp_dir)
    # SoulEngine 应该从文件恢复状态
    assert soul2._soul.fate.interaction_count > 0


def test_empty_message(tmp_dir):
    """空消息不崩"""
    soul = Soul(user_id="test_empty", data_dir=tmp_dir)
    r = soul.chat("")
    assert r.reply == ""


def test_soul_response_fields():
    """SoulResponse 有所有必要字段"""
    r = SoulResponse(reply="test")
    assert r.reply == "test"
    assert r.intent == {}
    assert r.generals == {}
    assert r.stage == ""
    assert r.frustration == 0.0
    assert r.evolution_notes == []
    assert r.interaction_count == 0
