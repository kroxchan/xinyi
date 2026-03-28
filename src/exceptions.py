"""语义化异常体系——替代模糊的 try/except + 通用错误字符串。"""
from __future__ import annotations


class XinyiBaseError(Exception):
    """所有 xinyi 自定义异常的基类。"""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint  # 给用户的建议操作

    def __str__(self) -> str:
        base = super().__str__()
        if self.hint:
            return f"{base}（提示：{self.hint}）"
        return base


class APIClientError(XinyiBaseError):
    """API 调用失败：连接错误、超时、401/403/500、无响应。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_retryable: bool = False,
    ) -> None:
        hint = "请检查 API Key、网络连接，或稍后重试"
        super().__init__(message, hint=hint)
        self.status_code = status_code
        self.is_retryable = is_retryable


class MemoryExtractionError(XinyiBaseError):
    """记忆 / 信念抽取失败：API 返回为空、JSON 解析失败、结果不符合预期 schema。"""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unknown",
        sample: str | None = None,
    ) -> None:
        reason_hint = {
            "api_empty": "模型返回为空，请检查 API 连接和 Key",
            "json_parse": "模型响应格式异常，请检查 API 是否正常",
            "schema_mismatch": "模型输出结构不符合预期，可尝试切换模型",
            "insufficient_data": "对话量不足，建议至少 30 条消息后再训练",
            "unknown": "未知原因，请查看日志或重试",
        }.get(reason, reason)
        super().__init__(message, hint=reason_hint)
        self.reason = reason
        self.sample = sample


class DecryptionError(XinyiBaseError):
    """微信数据库解密失败：Xcode 工具缺失、权限问题、数据库格式异常。"""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unknown",
    ) -> None:
        hint = {
            "xcode_missing": "请先安装 Xcode Command Line Tools：xcode-select --install",
            "db_locked": "数据库文件被占用，请关闭微信后重试",
            "db_corrupt": "数据库文件损坏，请重新导出聊天记录",
            "permission": "权限不足，请检查文件读取权限",
        }.get(reason, "请检查 Xcode 环境、数据库文件路径和权限")
        super().__init__(message, hint=hint)
        self.reason = reason


class ConfigError(XinyiBaseError):
    """配置错误：缺少必要配置项、格式错误、环境变量未设置。"""

    def __init__(self, message: str, *, missing_key: str | None = None) -> None:
        hint = f"请检查 .env 文件或 config.yaml 中是否配置了 {missing_key}" if missing_key else "请检查配置文件"
        super().__init__(message, hint=hint)
        self.missing_key = missing_key


class RerankError(XinyiBaseError):
    """重排模型失败：加载失败或推理失败，不影响主检索流程。"""

    def __init__(self, message: str, *, model: str | None = None) -> None:
        hint = "已自动回退到纯向量检索，功能不受影响。如需重排，请检查模型文件或网络"
        super().__init__(message, hint=hint)
        self.model = model


def exc_to_user_msg(exc: Exception) -> str:
    """将任意异常转换为用户友好的短提示。"""
    if isinstance(exc, XinyiBaseError):
        hint = exc.hint or ""
        return f"{exc}。{hint}" if hint else str(exc)

    exc_type = type(exc).__name__
    exc_str = str(exc).strip()

    # 常见异常模式 → 精确提示
    lower = exc_str.lower()
    if "connection" in lower or "connect" in lower:
        return f"API 连接失败（{exc_type}）。请检查网络连接和 API 地址是否正确"
    if "timeout" in lower or "timed out" in lower:
        return f"API 请求超时（{exc_type}）。请稍后重试，或检查 API 服务状态"
    if "401" in exc_str or "403" in exc_str or "unauthorized" in lower:
        return f"API 认证失败（{exc_type}）。请检查 API Key 是否正确"
    if "429" in exc_str or "rate limit" in lower or "RateLimitError" in exc_type or "rate_limit" in lower:
        return f"API 请求频率超限（{exc_type}）。请稍后重试"
    if "500" in exc_str or "502" in exc_str or "503" in exc_str:
        return f"API 服务端错误（{exc_type}）。这是服务端问题，请稍后重试"
    if "empty" in lower or "none" in lower or "returned null" in lower:
        return f"API 返回为空（{exc_type}）。请检查 API Key 和网络连接"
    if "json" in lower and ("decode" in lower or "parse" in lower):
        return f"API 响应格式解析失败（{exc_type}）。请检查 API 返回格式"

    # Fallback — keep full message, truncate only at 150 chars to avoid UI overflow
    fallback_msg = f"{exc_type}：{exc_str}" if exc_str else f"操作失败（{exc_type or 'UnknownError'}）"
    return fallback_msg[:150] if len(fallback_msg) > 150 else fallback_msg
