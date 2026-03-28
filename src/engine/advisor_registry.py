"""
src/engine/advisor_registry.py
统一管理所有需要热重载的 advisor 实例。
_save_api 触发 reload 后，下次 _get_advisor() 会用新配置重新初始化。
"""

import logging
from typing import Callable, Optional, List

logger = logging.getLogger(__name__)

# 全局单例
_instance: Optional["_AdvisorRegistry"] = None


def get_registry() -> "_AdvisorRegistry":
    global _instance
    if _instance is None:
        _instance = _AdvisorRegistry()
    return _instance


class _AdvisorRegistry:
    """
    保存各 tab 的 advisor 初始化函数（闭包已绑定 components），以及当前实例。
    reload() 把所有实例置 None，下次 get() 时用当前 components 重新创建。
    """

    def __init__(self) -> None:
        self._advisor_factory: Optional[Callable] = None
        self._mediator_factory: Optional[Callable] = None
        self._advisor_inst: List[Optional[object]] = [None]
        self._mediator_inst: List[Optional[object]] = [None]
        # 额外任意 key 的实例
        self._extra: dict = {}

    # ── 注册 factory ────────────────────────────────────────────────

    def register_advisor(self, factory: Callable) -> None:
        """factory() -> advisor 实例，在 tab 渲染时调用"""
        self._advisor_factory = factory
        self._advisor_inst[0] = None  # 清理旧实例

    def register_mediator(self, factory: Callable) -> None:
        self._mediator_factory = factory
        self._mediator_inst[0] = None

    def register_extra(self, key: str, factory: Callable) -> None:
        """通用注册槽位，供其他一次性热重载组件使用"""
        self._extra[key] = {"factory": factory, "inst": [None]}

    # ── 获取实例 ────────────────────────────────────────────────────

    def get_advisor(self):
        if self._advisor_inst[0] is None and self._advisor_factory is not None:
            self._advisor_inst[0] = self._advisor_factory()
        return self._advisor_inst[0]

    def get_mediator(self):
        if self._mediator_inst[0] is None and self._mediator_factory is not None:
            self._mediator_inst[0] = self._mediator_factory()
        return self._mediator_inst[0]

    def get_extra(self, key: str):
        slot = self._extra.get(key)
        if slot is None:
            return None
        if slot["inst"][0] is None:
            slot["inst"][0] = slot["factory"]()
        return slot["inst"][0]

    # ── 热重载入口 ───────────────────────────────────────────────────

    def reload(self) -> None:
        """_save_api 调用：把所有实例置 None，下次 get() 时用新 components 重建"""
        logger.info("AdvisorRegistry: 热重载，清理所有实例")
        self._advisor_inst[0] = None
        self._mediator_inst[0] = None
        for slot in self._extra.values():
            slot["inst"][0] = None
