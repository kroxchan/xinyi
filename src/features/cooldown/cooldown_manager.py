"""冲突后冷却管理器 (Conflict Cooldown Manager).

检测高强度负面情绪后，在 24 小时内：
1. 提示用户「等一等再发」
2. 在分身回复中注入冷静语气引导
3. 不重复打扰，但持续影响对话风格

不替代用户决策，只影响分身语气。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# 高强度负面情绪列表（触发冷却）
_HIGH_INTENSITY_NEGATIVE = {"anger", "wronged", "disappointment"}

# 普通负面情绪（需要更高置信度才触发）
_OTHER_NEGATIVE = {"sadness", "anxiety", "jealousy"}

# 冷却即将结束的阈值（小时）
_WINDING_DOWN_HOURS = 2.0


class ConflictCooldownManager:
    """冲突后冷却管理器。

    检测高强度负面情绪（anger/wronged/disappointment，置信度 >= 0.65）
    或其他负面情绪（置信度 >= 0.75）时，触发 24 小时冷却期。

    Attributes:
        cooldown_hours: 冷却时长（小时），默认 24 小时
        anger_threshold: anger 情绪的触发阈值
        negative_threshold: 其他负面情绪的触发阈值
        storage_path: 状态持久化路径
    """

    def __init__(
        self,
        cooldown_hours: float = 24.0,
        anger_threshold: float = 0.65,
        negative_threshold: float = 0.75,
        storage_path: str = "data/cooldown_state.json",
    ) -> None:
        self.cooldown_hours = cooldown_hours
        self.anger_threshold = anger_threshold
        self.negative_threshold = negative_threshold
        self.storage_path = Path(storage_path)

        self._state: dict | None = None  # 内存缓存
        self._dismissed: bool = False     # 用户是否已关闭提示
        self._load()

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从文件加载冷却状态。"""
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                self._state = data
                logger.debug("Loaded cooldown state: started=%s",
                             data.get("started_at"))
            except Exception as e:
                logger.warning("Failed to load cooldown state: %s", e)
                self._state = None

    def save(self) -> None:
        """将冷却状态保存到文件。"""
        if self._state is None:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save cooldown state: %s", e)

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def check_and_trigger(self, emotion: str, confidence: float) -> bool:
        """检查情绪状态，必要时触发新的冷却周期。

        Args:
            emotion: 当前情绪名称
            confidence: 情绪置信度（0.0-1.0）

        Returns:
            True 表示触发了新的冷却周期（即冷却已结束，刚检测到高情绪）
            False 表示未触发新冷却（已在冷却中，或未达到触发条件）
        """
        # 如果已经在冷却中，不重复触发
        if self.is_in_cooldown():
            return False

        # 检查是否达到触发条件
        if not self._should_trigger(emotion, confidence):
            return False

        # 触发新冷却
        self._state = {
            "started_at": time.time(),
            "trigger_emotion": emotion,
            "trigger_confidence": confidence,
        }
        self._dismissed = False
        self.save()
        logger.info("Cooldown triggered: emotion=%s confidence=%.2f", emotion, confidence)
        return True

    def _should_trigger(self, emotion: str, confidence: float) -> bool:
        """判断是否应该触发冷却。"""
        if emotion in _HIGH_INTENSITY_NEGATIVE:
            return confidence >= self.anger_threshold
        if emotion in _OTHER_NEGATIVE:
            return confidence >= self.negative_threshold
        return False

    def is_in_cooldown(self) -> bool:
        """当前是否处于冷却期。"""
        if self._state is None:
            return False
        elapsed = self.get_elapsed_hours()
        return 0 < elapsed < self.cooldown_hours

    def get_elapsed_hours(self) -> float:
        """冷却已过去多少小时。"""
        if self._state is None:
            return 0.0
        started = self._state.get("started_at", 0)
        if not started:
            return 0.0
        elapsed = time.time() - started
        return max(0.0, elapsed / 3600.0)

    def get_remaining_hours(self) -> float:
        """冷却还剩多少小时。"""
        remaining = self.cooldown_hours - self.get_elapsed_hours()
        return max(0.0, remaining)

    # ------------------------------------------------------------------
    # Prompt 生成
    # ------------------------------------------------------------------

    def get_cooldown_prompt(self) -> str:
        """返回分身系统 prompt 的附加内容（冷却期注入）。

        如果不在冷却期，返回空字符串。
        如果冷却即将结束（剩余 < 2h），语气可以逐渐恢复正常。
        """
        if not self.is_in_cooldown():
            return ""

        remaining = self.get_remaining_hours()
        trigger_emo = self._state.get("trigger_emotion", "未知") if self._state else "未知"

        if remaining >= _WINDING_DOWN_HOURS:
            template = _COOLDOWN_PROMPT_TEMPLATE
        else:
            template = _WINDING_DOWN_PROMPT_TEMPLATE

        return template.format(
            remaining=remaining,
            trigger_emotion=_EMOTION_LABELS.get(trigger_emo, trigger_emo),
        )

    def get_ui_message(self) -> str | None:
        """返回 UI 提示消息。

        仅在新冷却开始时触发一次。
        冷却中用户主动触发时返回 None（不重复打扰）。
        冷却即将结束时返回恢复提示。
        """
        if not self.is_in_cooldown():
            return None

        # 用户已主动关闭，不再打扰
        if self._dismissed:
            return None

        remaining = self.get_remaining_hours()
        if remaining >= _WINDING_DOWN_HOURS:
            return (
                "你们之间刚发生过一次高情绪对话。"
                "分身现在以更平静的语气回应你。"
                "冷却还会持续 {:.1f} 小时。".format(remaining)
            )
        else:
            return (
                "冷却快结束了。"
                "再过 {:.1f} 小时分身语气会恢复正常。".format(remaining)
            )

    def mark_ui_shown(self) -> None:
        """标记 UI 消息已显示（用户看到后不再打扰）。"""
        self._dismissed = True

    def dismiss(self) -> None:
        """用户主动关闭冷却提示（不影响冷却计时）。"""
        self._dismissed = True

    def reset(self) -> None:
        """手动重置冷却（用于测试或用户主动重置）。"""
        self._state = None
        self._dismissed = False
        if self.storage_path.exists():
            try:
                self.storage_path.unlink()
            except Exception as e:
                logger.warning("Failed to delete cooldown state: %s", e)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """返回当前冷却状态的完整信息（用于调试）。"""
        return {
            "is_in_cooldown": self.is_in_cooldown(),
            "elapsed_hours": self.get_elapsed_hours(),
            "remaining_hours": self.get_remaining_hours(),
            "trigger_emotion": self._state.get("trigger_emotion") if self._state else None,
            "trigger_confidence": self._state.get("trigger_confidence") if self._state else None,
            "dismissed": self._dismissed,
        }


# ------------------------------------------------------------------
# Prompt 模板
# ------------------------------------------------------------------

_COOLDOWN_PROMPT_TEMPLATE = """\
## 当前状态：情绪冷却期

你们之间刚发生过一次高情绪对话（触发情绪：{trigger_emotion}）。
你的另一半可能还带着情绪，或者正在等双方都冷静下来。

【你的任务】
- 不要急着「分析问题」或「讲道理」
- 不要急着「认错求和」或「非要给个说法」
- 如果对方还在冷战，不要追
- 如果对方发消息来了，回复要短、平，不要升级情绪

【语气提示】
- 比平时更短、更淡
- 不主动提刚才的事
- 等对方主动，或者等话题自然过去

【如果对方发了消息】
- 先接住情绪（一句「嗯」「知道了」「我也难受」就够了）
- 不要长篇大论，不要总结，不要给解决方案
- 留空间，不要逼

（冷却计时：{remaining:.1f}小时后结束，届时语气恢复正常）
"""

_WINDING_DOWN_PROMPT_TEMPLATE = """\
## 情绪冷却即将结束

冷却期快结束了（还剩{remaining:.1f}小时）。
你的另一半可能也在慢慢冷静下来。

【语气提示】
- 可以稍微放松一点，但不要突然变得太热情
- 不要主动提刚才的事，等对方自然提起
- 如果感觉气氛缓和了，回复可以稍微正常一些

（{remaining:.1f}小时后完全恢复正常语气）
"""

_EMOTION_LABELS: dict[str, str] = {
    "anger": "生气",
    "sadness": "难过",
    "anxiety": "焦虑",
    "disappointment": "失望",
    "wronged": "委屈",
    "jealousy": "吃醋",
}
