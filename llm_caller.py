#!/usr/bin/env python3
"""
共享 LLM 调用层 — 四引擎统一使用

复用 real_coder.py 的 API 调用模式：
- anthropic SDK: client.messages.create()
- API Key 从 config.json 加载
- 集成 CostGuardian 成本记录

模型分级：
- claude-sonnet-4-6: Commander / 高质量决策
- claude-haiku-4-5: Soldier / 轻量执行 / 辅助分析

Author: TaijiOS
Date: 2026-04-09
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

log = logging.getLogger("aios.llm_caller")

# ============================================================
# API 配置加载（复用 real_coder.py 模式）
# ============================================================

_config_cache = None


def _load_config() -> Dict:
    """加载 config.json"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_file = Path(__file__).parent / "config.json"
    if config_file.exists():
        try:
            with open(config_file, encoding="utf-8") as f:
                _config_cache = json.load(f)
                return _config_cache
        except Exception as e:
            log.warning(f"config.json 加载失败: {e}")

    _config_cache = {}
    return _config_cache


def _get_client():
    """获取 anthropic 客户端"""
    import anthropic

    config = _load_config()
    api_key = config.get("anthropic_api_key")
    base_url = config.get("anthropic_base_url") or None  # null → None

    if not api_key:
        import os
        api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        raise RuntimeError("未设置 API Key。请在 config.json 或 ANTHROPIC_API_KEY 环境变量中配置。")

    # 显式传 base_url，避免被 ANTHROPIC_BASE_URL 环境变量覆盖
    if not base_url:
        base_url = "https://api.anthropic.com"

    return anthropic.Anthropic(api_key=api_key, base_url=base_url)


# ============================================================
# 成本记录
# ============================================================

def _record_cost(model: str, input_tokens: int, output_tokens: int):
    """记录 API 调用成本"""
    try:
        from cost_guardian import CostGuardian
        cg = CostGuardian()
        cost = cg.calculate_cost(model, input_tokens, output_tokens)
        log.info(f"[LLM] model={model} in={input_tokens} out={output_tokens} cost=${cost:.4f}")
    except Exception:
        pass


# ============================================================
# 核心调用函数
# ============================================================

def call_llm(system_prompt: str,
             user_prompt: str,
             model: str = "claude-sonnet-4-6",
             max_tokens: int = 2048,
             temperature: float = 0.7) -> str:
    """
    调用 Claude API

    Args:
        system_prompt: 系统提示
        user_prompt: 用户提示
        model: 模型名称
        max_tokens: 最大输出 token
        temperature: 温度

    Returns:
        LLM 响应文本。失败时返回 "[LLM_ERROR] ..." 前缀字符串
    """
    try:
        client = _get_client()

        t0 = time.time()
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        elapsed = time.time() - t0

        text = message.content[0].text

        # 成本记录
        input_tokens = getattr(message.usage, "input_tokens", 0)
        output_tokens = getattr(message.usage, "output_tokens", 0)
        _record_cost(model, input_tokens, output_tokens)

        log.info(f"[LLM] OK model={model} time={elapsed:.1f}s tokens={input_tokens}+{output_tokens}")
        return text

    except Exception as e:
        log.error(f"[LLM] FAIL model={model} error={e}")
        return f"[LLM_ERROR] {e}"


def call_llm_json(system_prompt: str,
                  user_prompt: str,
                  model: str = "claude-sonnet-4-6",
                  max_tokens: int = 2048) -> Dict[str, Any]:
    """
    调用 Claude API 并解析 JSON 响应

    system_prompt 中应包含"请以 JSON 格式回答"等指令。

    Returns:
        解析后的 dict。失败时返回 {"error": "...", "raw": "..."}
    """
    text = call_llm(system_prompt, user_prompt, model, max_tokens)

    if text.startswith("[LLM_ERROR]"):
        return {"error": text, "raw": text}

    # 清理 markdown 代码块
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试找到第一个 { 和最后一个 }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
        return {"error": "JSON parse failed", "raw": text}


def is_llm_available() -> bool:
    """检查 LLM 是否可用（API Key 已配置）"""
    config = _load_config()
    api_key = config.get("anthropic_api_key")
    if api_key and api_key != "your-api-key-here":
        return True
    import os
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=== LLM Caller 测试 ===\n")

    print(f"LLM 可用: {is_llm_available()}")

    if is_llm_available():
        # 文本调用
        print("\n--- 文本调用 ---")
        result = call_llm(
            system_prompt="你是一个简洁的助手，用一句话回答。",
            user_prompt="TaijiOS 是什么？",
            model="claude-haiku-4-5",
            max_tokens=100,
        )
        print(f"响应: {result}")

        # JSON 调用
        print("\n--- JSON 调用 ---")
        result_json = call_llm_json(
            system_prompt="你是一个 JSON 生成器。请严格以 JSON 格式回答，不要包含其他内容。",
            user_prompt='分析这个错误：API timeout。返回 {"error_type": "...", "severity": "...", "suggestion": "..."}',
            model="claude-haiku-4-5",
            max_tokens=200,
        )
        print(f"JSON: {json.dumps(result_json, ensure_ascii=False, indent=2)}")
    else:
        print("⚠️ API Key 未配置，跳过实际调用")

    print("\n✅ LLM Caller 测试完成")
