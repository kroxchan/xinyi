"""冲突后冷却管理功能.

检测高强度负面情绪后，在 24 小时内：
1. 提示用户「等一等再发」
2. 在分身回复中注入冷静语气引导
3. 不重复打扰，但持续影响对话风格
"""

from src.features.cooldown.cooldown_manager import (
    ConflictCooldownManager,
    _HIGH_INTENSITY_NEGATIVE,
    _OTHER_NEGATIVE,
    _WINDING_DOWN_HOURS,
)

__all__ = [
    "ConflictCooldownManager",
]
