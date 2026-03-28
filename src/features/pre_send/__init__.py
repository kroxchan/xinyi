"""发前对齐 MVP — 让用户发送前先「对齐」一下理解。

用户想说一句话，但不确定对方会怎么理解。
粘贴草稿 → 系统输出：
1. 「对方可能听到的版本」：模拟 TA 的理解视角
2. 「TA 可能触发的情绪」：预测对方感受
3. 「一句话建议」：不评判，只给一个简单参考
4. 「可选改写」：提供 1-2 个语气不同的备选
"""

from src.features.pre_send.pre_send_engine import PreSendAligner

__all__ = ["PreSendAligner"]
