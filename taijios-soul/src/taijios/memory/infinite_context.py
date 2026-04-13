"""
InfiniteContext — 无限上下文模块

三层架构：热上下文 + 温缓存 + 冷存储
用户感受：AI永远记得所有事。
实际实现：只在需要的时候把相关记忆拉回来。
"""

import json
import time
import os
import hashlib
import logging
import threading
from collections import deque
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 中文分词 ──
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False
    logger.info("jieba not installed, falling back to character n-gram segmentation")


def segment_text(text: str) -> list[str]:
    """中文分词：优先jieba，退化为2/3-gram"""
    if _HAS_JIEBA:
        return [w for w in jieba.lcut(text) if w.strip()]
    return _char_ngram_segment(text)


def _char_ngram_segment(text: str) -> list[str]:
    """字符级2-gram/3-gram切分，作为无jieba时的fallback"""
    tokens = []
    # 先按空格和标点粗切
    chunks = []
    buf = []
    for ch in text:
        if ch in " \t\n\r，。！？、；：""''（）【】《》,.!?;:()[]{}\"'":
            if buf:
                chunks.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        chunks.append("".join(buf))

    for chunk in chunks:
        # ASCII词直接保留
        if chunk.isascii():
            if len(chunk) >= 2:
                tokens.append(chunk.lower())
            continue
        # 中文：生成2-gram和3-gram
        for n in (2, 3):
            for i in range(len(chunk) - n + 1):
                tokens.append(chunk[i:i + n])
    return tokens


# ── Token估算 ──
def estimate_tokens(text: str) -> int:
    """中文为主的token估算：1中文字≈1-2 token，取0.6系数"""
    return int(len(text) * 0.6)


# ============================================================
# Tier 1: 热上下文
# ============================================================

class HotContext:
    """
    热上下文：当前对话的原始消息。
    直接喂给LLM，不做压缩。
    有容量上限——超了就把最旧的消息压缩推到Tier2。
    线程安全：所有读写通过self._lock保护。
    """

    def __init__(self, max_turns: int = 20, max_tokens_estimate: int = 8000):
        self.messages: deque = deque(maxlen=max_turns * 2)
        self.max_tokens = max_tokens_estimate
        self.session_id: str = ""
        self.session_start: float = 0
        self.turn_count: int = 0
        self._lock = threading.Lock()

    def start_session(self, session_id: str = ""):
        with self._lock:
            self.session_id = session_id or hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
            self.session_start = time.time()
            self.turn_count = 0

    def add_turn(self, user_msg: str, assistant_msg: str):
        with self._lock:
            self.messages.append({"role": "user", "content": user_msg, "ts": time.time()})
            self.messages.append({"role": "assistant", "content": assistant_msg, "ts": time.time()})
            self.turn_count += 1

    def get_messages(self) -> list[dict]:
        with self._lock:
            return list(self.messages)

    def get_overflow(self) -> list[dict]:
        with self._lock:
            estimated_tokens = sum(estimate_tokens(m["content"]) for m in self.messages)
            overflow = []
            while estimated_tokens > self.max_tokens and len(self.messages) > 4:
                msg = self.messages.popleft()
                overflow.append(msg)
                estimated_tokens = sum(estimate_tokens(m["content"]) for m in self.messages)
            return overflow

    def get_context_for_llm(self) -> str:
        with self._lock:
            parts = []
            for msg in self.messages:
                role = "用户" if msg["role"] == "user" else "助手"
                parts.append(f"[{role}] {msg['content']}")
            return "\n".join(parts)

    def export_session(self) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "start_time": self.session_start,
                "end_time": time.time(),
                "turn_count": self.turn_count,
                "messages": list(self.messages),
            }

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "turn_count": self.turn_count,
                "message_count": len(self.messages),
                "estimated_tokens": sum(estimate_tokens(m["content"]) for m in self.messages),
            }


# ============================================================
# Tier 2: 温缓存
# ============================================================

@dataclass
class SessionSummary:
    """一个session的压缩摘要"""
    session_id: str
    timestamp: float
    duration_minutes: float
    turn_count: int
    summary: str
    topics: list[str]
    keywords: list[str]
    entities_mentioned: list[str]
    frustration_peak: float = 0.0
    relationship_stage: str = ""
    mutations_active: list[str] = field(default_factory=list)
    importance: float = 0.5
    message_count: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M"),
            "duration_min": round(self.duration_minutes, 1),
            "turns": self.turn_count,
            "summary": self.summary,
            "topics": self.topics,
            "keywords": self.keywords,
            "entities": self.entities_mentioned,
            "importance": round(self.importance, 2),
            "stage": self.relationship_stage,
        }

    @staticmethod
    def from_dict(d: dict) -> "SessionSummary":
        return SessionSummary(
            session_id=d["session_id"],
            timestamp=d["timestamp"],
            duration_minutes=d.get("duration_min", 0),
            turn_count=d.get("turns", 0),
            summary=d.get("summary", ""),
            topics=d.get("topics", []),
            keywords=d.get("keywords", []),
            entities_mentioned=d.get("entities", []),
            frustration_peak=d.get("frustration_peak", 0),
            relationship_stage=d.get("stage", ""),
            mutations_active=d.get("mutations", []),
            importance=d.get("importance", 0.5),
            message_count=d.get("message_count", 0),
        )

class WarmCache:
    """
    温缓存：最近几天的session摘要。
    按语义和时间检索，每次对话开始时预热。
    线程安全：所有读写通过self._lock保护。
    """

    MAX_SUMMARIES = 200
    ARCHIVE_THRESHOLD = 150
    RELEVANCE_TOP_K = 5

    def __init__(self, cache_path: str = None):
        self.cache_path = cache_path or "warm_cache.jsonl"
        self.summaries: list[SessionSummary] = []
        self._lock = threading.Lock()
        self._load()

    def add_summary(self, summary: SessionSummary):
        with self._lock:
            self.summaries.append(summary)
            self._save_append(summary)
            if len(self.summaries) > self.MAX_SUMMARIES:
                self._archive_oldest()

    def retrieve(self, query: str, top_k: int = None) -> list[SessionSummary]:
        k = top_k or self.RELEVANCE_TOP_K
        query_words = set(segment_text(query))

        with self._lock:
            scored = []
            now = time.time()
            for summary in self.summaries:
                summary_words = set(
                    w.lower() for w in
                    summary.keywords + summary.topics + summary.entities_mentioned
                )
                summary_words.update(segment_text(summary.summary))

                overlap = len(query_words & summary_words)
                keyword_score = overlap / max(len(query_words), 1)

                age_days = (now - summary.timestamp) / 86400
                time_score = 0.5 ** (age_days / 7)

                score = (
                    keyword_score * 0.5 +
                    time_score * 0.3 +
                    summary.importance * 0.2
                )
                if score > 0.05:
                    scored.append((score, summary))

            scored.sort(key=lambda x: -x[0])
            return [s for _, s in scored[:k]]

    def get_recent(self, count: int = 3) -> list[SessionSummary]:
        with self._lock:
            return self.summaries[-count:]

    def get_by_topic(self, topic: str) -> list[SessionSummary]:
        topic_lower = topic.lower()
        with self._lock:
            return [
                s for s in self.summaries
                if any(topic_lower in t.lower() for t in s.topics + s.keywords)
            ]

    def get_by_entity(self, entity: str) -> list[SessionSummary]:
        entity_lower = entity.lower()
        with self._lock:
            return [
                s for s in self.summaries
                if any(entity_lower in e.lower() for e in s.entities_mentioned)
            ]

    def _archive_oldest(self):
        """把最旧的摘要移到Tier3。调用方必须已持有self._lock。"""
        archive_count = len(self.summaries) - self.ARCHIVE_THRESHOLD
        if archive_count <= 0:
            return 0

        # 用scored副本排序，不改原列表顺序
        scored = sorted(
            enumerate(self.summaries),
            key=lambda x: x[1].importance * 0.3 + (x[1].timestamp / time.time()) * 0.7,
        )
        archive_indices = set(i for i, _ in scored[:archive_count])
        archived = [self.summaries[i] for i in sorted(archive_indices)]
        self.summaries = [s for i, s in enumerate(self.summaries) if i not in archive_indices]

        archive_path = self.cache_path.replace(".jsonl", "_archive.jsonl")
        try:
            with open(archive_path, "a", encoding="utf-8") as f:
                for s in archived:
                    f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to write archive %s: %s", archive_path, e)

        self._save_all()
        return len(archived)

    def _load(self):
        if not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.summaries.append(SessionSummary.from_dict(json.loads(line)))
                        except Exception as e:
                            logger.warning("Skipping corrupt line in %s: %s", self.cache_path, e)
        except Exception as e:
            logger.warning("Failed to load warm cache %s: %s", self.cache_path, e)

    def _save_append(self, summary: SessionSummary):
        try:
            with open(self.cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to append to %s: %s", self.cache_path, e)

    def _save_all(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                for s in self.summaries:
                    f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to rewrite %s: %s", self.cache_path, e)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "total_summaries": len(self.summaries),
                "oldest": datetime.fromtimestamp(self.summaries[0].timestamp).strftime("%Y-%m-%d") if self.summaries else "none",
                "newest": datetime.fromtimestamp(self.summaries[-1].timestamp).strftime("%Y-%m-%d") if self.summaries else "none",
                "total_turns": sum(s.turn_count for s in self.summaries),
            }


# ============================================================
# Tier 3: 冷存储
# ============================================================

class ColdStorage:
    """
    冷存储：所有历史的压缩归档。
    永不删除。磁盘级别存储。
    """

    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or "cold_storage"
        os.makedirs(self.storage_dir, exist_ok=True)
        self.milestones_path = os.path.join(self.storage_dir, "milestones.jsonl")
        self.archive_path = os.path.join(self.storage_dir, "session_archive.jsonl")
        self.grains_path = os.path.join(self.storage_dir, "cognitive_grains_snapshot.json")
        self.entity_path = os.path.join(self.storage_dir, "entity_graph_snapshot.json")

    def save_milestone(self, milestone: dict):
        milestone["saved_at"] = time.time()
        try:
            with open(self.milestones_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(milestone, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to save milestone to %s: %s", self.milestones_path, e)

    def save_grain_snapshot(self, grains: list[dict]):
        snapshot = {
            "timestamp": time.time(),
            "grain_count": len(grains),
            "grains": grains,
        }
        try:
            with open(self.grains_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save grain snapshot: %s", e)

    def save_entity_snapshot(self, entities: list[dict]):
        snapshot = {
            "timestamp": time.time(),
            "entity_count": len(entities),
            "entities": entities,
        }
        try:
            with open(self.entity_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save entity snapshot: %s", e)

    def search_archive(self, query: str, max_results: int = 10) -> list[dict]:
        if not os.path.exists(self.archive_path):
            return []
        query_words = set(segment_text(query))
        results = []
        try:
            with open(self.archive_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        text = " ".join([
                            entry.get("summary", ""),
                            " ".join(entry.get("topics", [])),
                            " ".join(entry.get("keywords", [])),
                        ])
                        text_words = set(segment_text(text))
                        overlap = len(query_words & text_words)
                        if overlap > 0:
                            results.append((overlap, entry))
                    except Exception as e:
                        logger.warning("Skipping corrupt archive line: %s", e)
        except Exception as e:
            logger.warning("Failed to read archive %s: %s", self.archive_path, e)
        results.sort(key=lambda x: -x[0])
        return [r for _, r in results[:max_results]]

    def get_milestones(self, count: int = 20) -> list[dict]:
        if not os.path.exists(self.milestones_path):
            return []
        milestones = []
        try:
            with open(self.milestones_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            milestones.append(json.loads(line))
                        except Exception as e:
                            logger.warning("Skipping corrupt milestone line: %s", e)
        except Exception as e:
            logger.warning("Failed to read milestones %s: %s", self.milestones_path, e)
        return milestones[-count:]

    def to_dict(self) -> dict:
        archive_count = 0
        if os.path.exists(self.archive_path):
            try:
                with open(self.archive_path, "r") as f:
                    archive_count = sum(1 for _ in f)
            except Exception as e:
                logger.warning("Failed to count archive lines: %s", e)
        milestone_count = 0
        if os.path.exists(self.milestones_path):
            try:
                with open(self.milestones_path, "r") as f:
                    milestone_count = sum(1 for _ in f)
            except Exception as e:
                logger.warning("Failed to count milestone lines: %s", e)
        return {
            "archived_sessions": archive_count,
            "milestones": milestone_count,
            "has_grain_snapshot": os.path.exists(self.grains_path),
            "has_entity_snapshot": os.path.exists(self.entity_path),
        }


# ============================================================
# 上下文压缩器
# ============================================================

class ContextCompressor:
    """
    把原始对话压缩成摘要。
    用segment_text做中文分词（jieba或n-gram fallback）。
    """

    STOP_WORDS = {
        "的", "了", "是", "我", "你", "他", "她", "它",
        "在", "有", "和", "不", "这", "那", "就", "也",
        "都", "要", "会", "可以", "一个", "什么", "怎么",
        "吗", "吧", "呢", "啊", "哦", "嗯", "好",
        "the", "a", "an", "is", "are", "was", "were",
        "i", "you", "he", "she", "it", "we", "they",
        "to", "in", "on", "at", "for", "with", "from",
    }

    def compress_session(self, session_data: dict,
                          soul_context: dict = None) -> SessionSummary:
        messages = session_data.get("messages", [])
        session_id = session_data.get("session_id", "unknown")
        start_time = session_data.get("start_time", time.time())
        end_time = session_data.get("end_time", time.time())
        turn_count = session_data.get("turn_count", len(messages) // 2)

        user_texts = [m["content"] for m in messages if m.get("role") == "user"]
        all_text = " ".join(user_texts)

        keywords = self._extract_keywords(all_text, top_k=10)
        topics = self._infer_topics(user_texts)
        entities = self._extract_entities(all_text)
        summary = self._generate_summary(user_texts, keywords, topics)
        importance = self._assess_importance(messages, soul_context)

        frust_peak = 0.0
        stage = ""
        mutations = []
        if soul_context:
            frust_peak = soul_context.get("frustration_peak", 0)
            stage = soul_context.get("relationship_stage", "")
            mutations = [m.get("name", str(m)) for m in soul_context.get("active_mutations", [])]

        return SessionSummary(
            session_id=session_id,
            timestamp=start_time,
            duration_minutes=(end_time - start_time) / 60,
            turn_count=turn_count,
            summary=summary,
            topics=topics,
            keywords=keywords,
            entities_mentioned=entities,
            frustration_peak=frust_peak,
            relationship_stage=stage,
            mutations_active=mutations,
            importance=importance,
            message_count=len(messages),
        )

    def compress_overflow(self, messages: list[dict]) -> str:
        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return ""
        if len(user_msgs) <= 4:
            selected = user_msgs
        else:
            selected = user_msgs[:3] + ["..."] + user_msgs[-1:]
        return "（之前的对话摘要：" + "；".join(m[:30] for m in selected) + "）"

    def _extract_keywords(self, text: str, top_k: int = 10) -> list[str]:
        """用segment_text分词后做TF关键词提取"""
        words = [w.lower() for w in segment_text(text) if len(w) >= 2 and w.lower() not in self.STOP_WORDS]
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: -x[1])
        return [w for w, _ in sorted_words[:top_k]]

    def _infer_topics(self, user_texts: list[str]) -> list[str]:
        topic_indicators = {
            "代码": ["代码", "bug", "报错", "函数", "变量", "debug", "编程"],
            "设计": ["设计", "UI", "界面", "布局", "样式", "颜色"],
            "架构": ["架构", "模块", "系统", "框架", "重构", "拆分"],
            "性能": ["性能", "慢", "优化", "内存", "泄漏", "速度"],
            "部署": ["部署", "上线", "服务器", "docker", "运维"],
            "学习": ["学习", "教程", "怎么", "入门", "理解"],
            "项目": ["项目", "需求", "进度", "deadline", "交付"],
            "闲聊": ["哈哈", "谢谢", "好的", "嗯", "你好"],
        }
        all_text = " ".join(user_texts).lower()
        topics = []
        for topic, indicators in topic_indicators.items():
            if any(ind in all_text for ind in indicators):
                topics.append(topic)
        return topics or ["一般对话"]

    def _extract_entities(self, text: str) -> list[str]:
        words = segment_text(text)
        freq = {}
        for w in words:
            if 2 <= len(w) <= 4 and w not in self.STOP_WORDS:
                freq[w] = freq.get(w, 0) + 1
        entities = [w for w, count in freq.items() if count >= 3]
        return entities[:10]

    def _generate_summary(self, user_texts: list[str], keywords: list[str],
                           topics: list[str]) -> str:
        if not user_texts:
            return "空对话"
        topic_str = "、".join(topics[:3])
        keyword_str = "、".join(keywords[:5])
        turn_count = len(user_texts)
        first = user_texts[0][:50]
        last = user_texts[-1][:50] if len(user_texts) > 1 else ""
        summary = f"关于{topic_str}的对话（{turn_count}轮）。"
        summary += f"从「{first}」开始"
        if last:
            summary += f"，到「{last}」结束"
        summary += f"。关键词：{keyword_str}。"
        return summary

    def _assess_importance(self, messages: list[dict],
                            soul_context: dict = None) -> float:
        importance = 0.5
        if len(messages) > 20:
            importance += 0.1
        if len(messages) > 40:
            importance += 0.1
        if soul_context:
            if soul_context.get("frustration_peak", 0) > 0.5:
                importance += 0.1
            if soul_context.get("active_mutations"):
                importance += 0.05
        for msg in messages:
            content = msg.get("content", "").lower()
            if any(w in content for w in ["记住", "重要", "deadline", "关键"]):
                importance += 0.15
                break
        return min(1.0, importance)


# ============================================================
# 主引擎：InfiniteContext
# ============================================================

class InfiniteContext:
    """
    无限上下文引擎。

    用法：
        ctx = InfiniteContext(user_id="user_001")
        ctx.start_session()
        preload = ctx.preload_context("帮我看看Python代码")
        ctx.add_turn(user_msg, assistant_msg)
        overflow_summary = ctx.check_overflow()
        ctx.end_session(soul_context={...})
    """

    def __init__(self, user_id: str, data_dir: str = None):
        self.user_id = user_id
        self.data_dir = data_dir or os.path.join("context_data", user_id)
        os.makedirs(self.data_dir, exist_ok=True)

        self.hot = HotContext()
        self.warm = WarmCache(
            cache_path=os.path.join(self.data_dir, "warm_cache.jsonl"),
        )
        self.cold = ColdStorage(
            storage_dir=os.path.join(self.data_dir, "cold"),
        )
        self.compressor = ContextCompressor()
        self._overflow_buffer: str = ""

    def start_session(self, session_id: str = ""):
        self.hot.start_session(session_id)
        self._overflow_buffer = ""

    def add_turn(self, user_msg: str, assistant_msg: str):
        self.hot.add_turn(user_msg, assistant_msg)

    def check_overflow(self) -> Optional[str]:
        overflow = self.hot.get_overflow()
        if not overflow:
            return None
        compressed = self.compressor.compress_overflow(overflow)
        self._overflow_buffer = compressed
        return compressed

    def preload_context(self, query: str) -> dict:
        recent = self.warm.get_recent(2)
        recent_texts = [
            f"[{s.to_dict()['date']}] {s.summary}" for s in recent
        ]
        relevant = self.warm.retrieve(query, top_k=3)
        relevant_texts = [
            f"[{s.to_dict()['date']}] {s.summary}"
            for s in relevant
            if s.session_id != self.hot.session_id
        ]

        cold_results = self.cold.search_archive(query, max_results=2)
        cold_texts = [
            f"[{r.get('date', '?')}] {r.get('summary', '')}"
            for r in cold_results
        ]
        parts = []
        if self._overflow_buffer:
            parts.append(self._overflow_buffer)
        if recent_texts:
            parts.append("最近的对话：" + " | ".join(recent_texts))
        if relevant_texts:
            parts.append("相关历史：" + " | ".join(relevant_texts))
        if cold_texts:
            parts.append("更早的记忆：" + " | ".join(cold_texts))
        context_block = "\n".join(parts) if parts else ""
        return {
            "overflow_summary": self._overflow_buffer,
            "recent_sessions": recent_texts,
            "relevant_history": relevant_texts,
            "cold_results": cold_texts,
            "context_block": context_block,
        }

    def end_session(self, soul_context: dict = None):
        if self.hot.turn_count == 0:
            return
        session_data = self.hot.export_session()
        summary = self.compressor.compress_session(session_data, soul_context)
        self.warm.add_summary(summary)
        if summary.importance > 0.8:
            self.cold.save_milestone({
                "type": "important_session",
                "session_id": summary.session_id,
                "summary": summary.summary,
                "importance": summary.importance,
            })

    def save_milestone(self, milestone: dict):
        self.cold.save_milestone(milestone)

    def get_stats(self) -> dict:
        return {
            "hot": self.hot.to_dict(),
            "warm": self.warm.to_dict(),
            "cold": self.cold.to_dict(),
        }

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "stats": self.get_stats(),
        }


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    import shutil

    print("=" * 60)
    print("  InfiniteContext — 无限上下文")
    print("  AI永远记得所有事")
    print("=" * 60)

    test_dir = "/tmp/infinite_ctx_test"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    ctx = InfiniteContext(user_id="test_user", data_dir=test_dir)

    # ── Session 1: 代码debug ──
    print("\n── Session 1: 代码debug ──")
    ctx.start_session("s001")
    ctx.add_turn("帮我看看Python代码有个bug", "好的，请把代码发给我")
    ctx.add_turn("TypeError那个错误", "这是类型不匹配，你需要转换")
    ctx.add_turn("还是报错", "检查一下变量类型")
    ctx.add_turn("好了解决了谢谢", "不客气")
    ctx.end_session(soul_context={"relationship_stage": "familiar", "frustration_peak": 0.3})
    print(f"  {ctx.hot.turn_count}轮对话已压缩存储")

    # ── Session 2: 架构讨论 ──
    print("\n── Session 2: 架构讨论 ──")
    ctx.start_session("s002")
    ctx.add_turn("TaijiOS的架构怎么优化", "可以考虑模块解耦")
    ctx.add_turn("EventBus的性能够吗", "目前的实现足够，瓶颈在LLM调用")
    ctx.add_turn("老张说要加缓存", "缓存可以，但要注意一致性")
    ctx.end_session(soul_context={"relationship_stage": "acquainted", "frustration_peak": 0.1})
    print(f"  {ctx.hot.turn_count}轮对话已压缩存储")

    # ── Session 3: 新对话，检索历史 ──
    print("\n── Session 3: 新对话 + 历史预热 ──")
    ctx.start_session("s003")
    preload = ctx.preload_context("Python bug修复")
    print("  预热结果:")
    print(f"    最近session: {len(preload['recent_sessions'])}条")
    print(f"    相关历史: {len(preload['relevant_history'])}条")
    if preload["context_block"]:
        print(f"    上下文块（前100字）: {preload['context_block'][:100]}...")

    # ── 统计 ──
    print("\n── 三层存储统计 ──")
    stats = ctx.get_stats()
    hot = stats["hot"]
    warm = stats["warm"]
    cold = stats["cold"]
    print(f"  Tier 1 热上下文: {hot['message_count']}条消息, ~{hot['estimated_tokens']}tokens")
    print(f"  Tier 2 温缓存:  {warm['total_summaries']}个session摘要")
    print(f"  Tier 3 冷存储:  {cold['archived_sessions']}个归档 + {cold['milestones']}个里程碑")

    # ── 按话题检索 ──
    print("\n── 按话题检索 ──")
    results = ctx.warm.get_by_topic("代码")
    print(f"  '代码'相关: {len(results)}个session")
    for r in results:
        print(f"    [{r.to_dict()['date']}] {r.summary[:50]}...")

    results = ctx.warm.get_by_entity("老张")
    print(f"  '老张'相关: {len(results)}个session")

    shutil.rmtree(test_dir)

    print(f"\n{'=' * 60}")
    print("  三层架构：热(当前) + 温(语义检索) + 冷(永久归档)")
    print("  用户感受：AI永远记得。")
    print("  实际实现：只在需要时拉回来。")
    print(f"{'=' * 60}")
