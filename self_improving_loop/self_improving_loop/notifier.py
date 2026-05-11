"""
Telegram Notifier - Self-Improving Loop 通知

在关键事件发生时推送 Telegram 通知：
1. 改进应用时推送
2. 回滚时告警
3. 每日统计报告（可选）

使用 OpenClaw 的 message 工具发送通知。
"""

from datetime import datetime
from typing import Dict


class TelegramNotifier:
    """Telegram 通知管理器"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def notify_improvement(self, agent_id: str, improvements_applied: int, details: Dict = None):
        """
        改进应用通知

        Args:
            agent_id: Agent ID
            improvements_applied: 应用的改进数量
            details: 改进详情
        """
        if not self.enabled:
            return

        message = "🔧 Self-Improving Loop\n\n"
        message += f"Agent: {agent_id}\n"
        message += f"应用了 {improvements_applied} 项自动改进\n"
        
        if details:
            message += "\n详情:\n"
            for key, value in details.items():
                message += f"  • {key}: {value}\n"
        
        message += f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self._send_message(message)

    def notify_rollback(self, agent_id: str, reason: str, metrics: Dict = None):
        """
        回滚告警

        Args:
            agent_id: Agent ID
            reason: 回滚原因
            metrics: 指标对比
        """
        if not self.enabled:
            return

        message = "⚠️ 自动回滚告警\n\n"
        message += f"Agent: {agent_id}\n"
        message += f"原因: {reason}\n"
        
        if metrics:
            before = metrics.get("before_metrics", {})
            after = metrics.get("after_metrics", {})
            
            message += "\n指标对比:\n"
            if "success_rate" in before:
                message += f"  • 成功率: {before['success_rate']:.1%} → {after.get('success_rate', 0):.1%}\n"
            if "avg_duration_sec" in before:
                message += f"  • 平均耗时: {before['avg_duration_sec']:.1f}s → {after.get('avg_duration_sec', 0):.1f}s\n"
        
        message += "\n已自动回滚到上一个配置"
        message += f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self._send_message(message, priority="high")

    def notify_daily_summary(self, stats: Dict):
        """
        每日统计报告

        Args:
            stats: 统计数据
        """
        if not self.enabled:
            return

        message = "📊 Self-Improving Loop 每日报告\n\n"
        message += f"总 Agent: {stats.get('total_agents', 0)}\n"
        message += f"总改进次数: {stats.get('total_improvements', 0)}\n"
        message += f"总回滚次数: {stats.get('total_rollbacks', 0)}\n"
        
        improved = stats.get('agents_improved', [])
        if improved:
            message += f"\n已改进 Agent ({len(improved)}):\n"
            for agent in improved[:5]:
                message += f"  • {agent}\n"
            if len(improved) > 5:
                message += f"  ... 还有 {len(improved) - 5} 个\n"
        
        rolled_back = stats.get('agents_rolled_back', [])
        if rolled_back:
            message += f"\n已回滚 Agent ({len(rolled_back)}):\n"
            for agent in rolled_back[:5]:
                message += f"  • {agent}\n"
        
        message += f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self._send_message(message)

    def notify_threshold_adjusted(self, agent_id: str, profile: Dict):
        """
        阈值调整通知（可选）

        Args:
            agent_id: Agent ID
            profile: Agent 配置文件
        """
        if not self.enabled:
            return

        message = "⚙️ 自适应阈值调整\n\n"
        message += f"Agent: {agent_id}\n"
        message += f"频率: {profile.get('frequency', 'unknown')}\n"
        message += f"任务数/天: {profile.get('tasks_per_day', 0)}\n"
        message += "\n新阈值:\n"
        message += f"  • 失败阈值: {profile.get('failure_threshold', 0)} 次\n"
        message += f"  • 分析窗口: {profile.get('analysis_window_hours', 0)} 小时\n"
        message += f"  • 冷却期: {profile.get('cooldown_hours', 0)} 小时\n"
        
        if profile.get('is_critical'):
            message += "\n⚠️ 关键任务 Agent"
        
        message += f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self._send_message(message)

    def _send_message(self, message: str, priority: str = "normal"):
        """
        发送 Telegram 消息

        Args:
            message: 消息内容
            priority: 优先级（normal/high）
        """
        # 这里应该调用 OpenClaw 的 message 工具
        # 简化版：只打印到日志
        print(f"[Telegram] {priority.upper()}: {message}")
        
        # 实际使用时，应该这样调用：
        # from openclaw import message
        # message.send(
        #     action="send",
        #     channel="telegram",
        #     message=message,
        #     silent=(priority != "high")
        # )


# ============================================================================
# 使用示例
# ============================================================================

def example_usage():
    """使用示例"""
    notifier = TelegramNotifier(enabled=True)

    # 1. 改进应用通知
    print("示例 1: 改进应用通知")
    notifier.notify_improvement(
        agent_id="coder-001",
        improvements_applied=2,
        details={
            "超时调整": "30s → 45s",
            "重试机制": "添加指数退避"
        }
    )

    print("\n" + "="*60 + "\n")

    # 2. 回滚告警
    print("示例 2: 回滚告警")
    notifier.notify_rollback(
        agent_id="coder-001",
        reason="成功率下降 15.0% (从 80.0% 到 65.0%)",
        metrics={
            "before_metrics": {
                "success_rate": 0.80,
                "avg_duration_sec": 10.0
            },
            "after_metrics": {
                "success_rate": 0.65,
                "avg_duration_sec": 12.0
            }
        }
    )

    print("\n" + "="*60 + "\n")

    # 3. 每日统计报告
    print("示例 3: 每日统计报告")
    notifier.notify_daily_summary({
        "total_agents": 9,
        "total_improvements": 5,
        "total_rollbacks": 1,
        "agents_improved": ["coder-001", "analyst-002", "monitor-003"],
        "agents_rolled_back": ["coder-001"]
    })

    print("\n" + "="*60 + "\n")

    # 4. 阈值调整通知
    print("示例 4: 阈值调整通知")
    notifier.notify_threshold_adjusted(
        agent_id="coder-001",
        profile={
            "frequency": "high",
            "tasks_per_day": 15,
            "failure_threshold": 5,
            "analysis_window_hours": 48,
            "cooldown_hours": 3,
            "is_critical": False
        }
    )


if __name__ == "__main__":
    example_usage()
