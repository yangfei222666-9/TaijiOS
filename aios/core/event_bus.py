"""
AIOS v0.6 EventBus - 系统心脏
职责：
1. 统一发布事件
2. 统一订阅事件
3. 统一日志存储（使用 EventStore）

禁止：
- 业务逻辑
- 直接调用其他模块
"""
import json
import gzip
from pathlib import Path
from typing import Callable, Dict, List, Optional
from collections import defaultdict
import fnmatch

from .event import Event

# 使用新的 Storage Manager（通过适配器）
try:
    from aios.storage.event_store_adapter import EventStoreAdapter, get_event_store_adapter
except ImportError:
    class EventStoreAdapter:
        """Small JSONL event store used when the optional storage package is absent."""

        def __init__(self, base_dir: Optional[Path] = None):
            aios_root = Path(__file__).resolve().parent.parent
            self.base_dir = base_dir or aios_root / "data" / "events"
            self.archive_dir = self.base_dir / "archive"
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self.archive_dir.mkdir(parents=True, exist_ok=True)

        def _event_file(self) -> Path:
            return self.base_dir / "events.jsonl"

        def append(self, event: Event) -> None:
            with self._event_file().open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        def load_events(
            self,
            event_type: Optional[str] = None,
            since: Optional[int] = None,
            limit: Optional[int] = None,
        ) -> List[Event]:
            events: List[Event] = []
            for path in sorted(self.base_dir.glob("*.jsonl")):
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = Event.from_dict(json.loads(line))
                        except (json.JSONDecodeError, TypeError, ValueError):
                            continue
                        if event_type and not fnmatch.fnmatch(event.type, event_type):
                            continue
                        if since is not None and event.timestamp < since:
                            continue
                        events.append(event)

            for path in sorted(self.archive_dir.glob("*.jsonl.gz")):
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = Event.from_dict(json.loads(line))
                        except (json.JSONDecodeError, TypeError, ValueError):
                            continue
                        if event_type and not fnmatch.fnmatch(event.type, event_type):
                            continue
                        if since is not None and event.timestamp < since:
                            continue
                        events.append(event)

            events.sort(key=lambda event: event.timestamp)
            return events[-limit:] if limit else events

        def migrate_from_single_file(self, old_file: Path) -> int:
            migrated = 0
            with old_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self.append(Event.from_dict(json.loads(line)))
                        migrated += 1
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            return migrated

    _fallback_store: Optional[EventStoreAdapter] = None

    def get_event_store_adapter() -> EventStoreAdapter:
        global _fallback_store
        if _fallback_store is None:
            _fallback_store = EventStoreAdapter()
        return _fallback_store


class EventBus:
    """事件总线 - 系统心脏（v0.6 使用 EventStore）"""
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化 EventBus
        
        Args:
            storage_path: 事件存储路径（兼容旧版，新版使用 EventStore）
        """
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        
        # 使用新的 EventStoreAdapter（基于 Storage Manager）
        self.store = get_event_store_adapter()
        
        # 兼容旧版：如果指定了 storage_path，尝试迁移
        if storage_path:
            old_file = Path(storage_path)
            if old_file.exists() and old_file.suffix == ".jsonl":
                print(f"[EventBus] Migrating from {old_file}...")
                count = self.store.migrate_from_single_file(old_file)
                print(f"[EventBus] Migrated {count} events")
    
    def emit(self, event: Event) -> None:
        """
        发布事件
        
        1. 验证事件
        2. 持久化到文件
        3. 通知所有订阅者
        
        Args:
            event: 事件对象
            
        Raises:
            ValueError: 事件验证失败
        """
        # 1. 验证事件
        self._validate_event(event)
        
        # 2. 持久化
        self._store(event)
        
        # 3. 通知订阅者
        self._notify_subscribers(event)
    
    def _validate_event(self, event: Event) -> None:
        """
        验证事件合法性
        
        Args:
            event: 事件对象
            
        Raises:
            ValueError: 验证失败
        """
        # 检查 type（Event 使用 type 不是 event_type）
        if not event.type or not isinstance(event.type, str):
            raise ValueError("type must be a non-empty string")
        
        if len(event.type) > 200:
            raise ValueError("type too long (max 200 chars)")
        
        # 检查 type 格式（只允许字母、数字、点、下划线、连字符）
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', event.type):
            raise ValueError("type contains invalid characters")
        
        # 检查 payload 大小（防止过大的 payload）
        if event.payload:
            import sys
            data_size = sys.getsizeof(str(event.payload))
            if data_size > 1024 * 1024:  # 1MB
                raise ValueError(f"event payload too large ({data_size} bytes, max 1MB)")
    
    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """
        订阅事件
        
        支持通配符：
        - "agent.*" 匹配所有 agent 事件
        - "*.error" 匹配所有 error 事件
        - "*" 匹配所有事件
        
        Args:
            event_type: 事件类型（支持通配符）
            handler: 处理函数
        """
        self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """
        取消订阅
        
        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)
    
    def _store(self, event: Event) -> None:
        """
        持久化事件到文件（使用 EventStore）
        
        Args:
            event: 事件对象
        """
        self.store.append(event)
    
    def _notify_subscribers(self, event: Event) -> None:
        """
        通知所有匹配的订阅者
        
        Args:
            event: 事件对象
        """
        for pattern, handlers in self._subscribers.items():
            if self._match_pattern(event.type, pattern):
                for handler in handlers:
                    try:
                        handler(event)
                    except Exception as e:
                        # 订阅者错误不应该影响事件发布
                        print(f"[EventBus] Subscriber error: {e}")
    
    @staticmethod
    def _match_pattern(event_type: str, pattern: str) -> bool:
        """
        匹配事件类型和模式
        
        Args:
            event_type: 事件类型
            pattern: 模式（支持通配符）
        
        Returns:
            是否匹配
        """
        return fnmatch.fnmatch(event_type, pattern)
    
    def load_events(
        self,
        event_type: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Event]:
        """
        加载历史事件（使用 EventStore）
        
        Args:
            event_type: 事件类型过滤（支持通配符）
            since: 时间戳过滤（毫秒）
            limit: 最大数量
        
        Returns:
            事件列表
        """
        return self.store.load_events(
            event_type=event_type,
            since=since,
            limit=limit
        )
    
    def count_events(self, event_type: Optional[str] = None, since: Optional[int] = None) -> int:
        """
        统计事件数量
        
        Args:
            event_type: 事件类型过滤（支持通配符）
            since: 时间戳过滤（毫秒）
        
        Returns:
            事件数量
        """
        return len(self.load_events(event_type=event_type, since=since))
    
    def clear_events(self) -> None:
        """清空所有事件（谨慎使用）"""
        # 清空所有日期文件
        for file_path in self.store.base_dir.glob("*.jsonl"):
            file_path.unlink()
        for file_path in self.store.archive_dir.glob("*.jsonl.gz"):
            file_path.unlink()


# 全局单例
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局 EventBus 实例"""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


# 便捷函数
def emit(event: Event) -> None:
    """发布事件（使用全局 EventBus）"""
    get_event_bus().emit(event)


def subscribe(event_type: str, handler: Callable[[Event], None]) -> None:
    """订阅事件（使用全局 EventBus）"""
    get_event_bus().subscribe(event_type, handler)
