"""UX 辅助函数 — 统一错误/进度/状态展示

所有 UI 层的友好提示、格式化的错误消息、状态卡片
都应通过此模块提供，确保视觉风格和提示措辞一致。
"""
from __future__ import annotations

from enum import Enum


# ==============================================================================
# 配色常量（与现有 UI 风格保持一致）
# ==============================================================================

_COLORS = {
    "success": "#65a88a",   # 绿色 — 成功/完成
    "error":   "#f87171",   # 红色 — 错误/失败
    "warning": "#fbbf24",   # 琥珀 — 警告/进行中
    "info":    "#a78bfa",   # 紫色 — 信息/强调
    "muted":   "#8c7b7f",   # 灰色 — 次要文字
    "bg_err":  "#fee2e2",   # 浅红背景
    "bg_warn": "#fef3c7",   # 浅黄背景
    "bg_ok":   "#ecfdf5",   # 浅绿背景
}


# ==============================================================================
# StatusLevel — 状态级别枚举
# ==============================================================================

class StatusLevel(Enum):
    SUCCESS  = "success"
    WARNING  = "warning"
    ERROR    = "error"
    INFO     = "info"
    LOADING  = "loading"

    @property
    def icon(self) -> str:
        return {
            "success":  "✅",
            "warning":  "⚠️",
            "error":    "❌",
            "info":     "ℹ️",
            "loading":  "⏳",
        }[self.value]

    @property
    def color(self) -> str:
        return _COLORS[self.value]


# ==============================================================================
# UXHelper — 核心格式化工具
# ==============================================================================

class UXHelper:
    """统一格式化 UX 反馈的辅助类。"""

    # --------------------------------------------------------------------------
    # 错误消息
    # --------------------------------------------------------------------------

    @staticmethod
    def format_error(
        title: str,
        message: str,
        solution: str | None = None,
        docs_url: str | None = None,
    ) -> str:
        """格式化错误信息卡片（含解决方案引导）。

        Args:
            title: 错误类型/标题
            message: 错误描述
            solution: 解决步骤（支持换行）
            docs_url: 可选的文档链接

        Example:
            >>> UXHelper.format_error(
            ...     title="API 连接失败",
            ...     message="无法连接到 AI 服务",
            ...     solution="1. 检查 API Key 是否正确\\n2. 检查网络连接",
            ... )
        """
        sol_html = ""
        if solution:
            sol_html = (
                '<div style="margin-top:12px;padding-top:12px;'
                'border-top:1px solid #fca5a5">'
                '<div style="font-weight:600;color:#991b1b;margin-bottom:4px">'
                '💡 解决方案</div>'
                f'<div style="color:#7f1d1d;white-space:pre-wrap">{solution}</div>'
                '</div>'
            )
        docs_html = (
            f'<div style="margin-top:8px">'
            f'<a href="{docs_url}" target="_blank" style="color:#a78bfa">📖 查看文档</a>'
            f'</div>'
            if docs_url else ""
        )
        return (
            f'<div style="padding:14px 16px;border-left:4px solid #dc2626;'
            f'background:#fee2e2;border-radius:4px;margin:8px 0">'
            f'<div style="font-weight:600;color:#991b1b">❌ {title}</div>'
            f'<div style="margin-top:4px;color:#7f1d1d">{message}</div>'
            f'{sol_html}{docs_html}'
            f'</div>'
        )

    @staticmethod
    def format_warning(title: str, message: str, hint: str | None = None) -> str:
        """格式化警告消息卡片。"""
        hint_html = (
            f'<div style="margin-top:8px;color:#92400e">{hint}</div>' if hint else ""
        )
        return (
            f'<div style="padding:14px 16px;border-left:4px solid #f59e0b;'
            f'background:#fef3c7;border-radius:4px;margin:8px 0">'
            f'<div style="font-weight:600;color:#92400e">⚠️ {title}</div>'
            f'<div style="margin-top:4px;color:#78350f">{message}</div>'
            f'{hint_html}'
            f'</div>'
        )

    # --------------------------------------------------------------------------
    # 成功 / 进度 / 加载
    # --------------------------------------------------------------------------

    @staticmethod
    def format_success(message: str) -> str:
        """简单的成功提示行。"""
        return f'<span style="color:#65a88a">✅ {message}</span>'

    @staticmethod
    def format_loading(message: str = "加载中...") -> str:
        """简单的加载提示行。"""
        return f'<span style="color:#8c7b7f">⏳ {message}</span>'

    @staticmethod
    def format_info(message: str) -> str:
        """简单的提示信息行。"""
        return f'<span style="color:#a78bfa">ℹ️ {message}</span>'

    @staticmethod
    def format_hint(message: str) -> str:
        """灰色辅助提示（次要信息）。"""
        return f'<span style="color:#8c7b7f;font-size:.9em">{message}</span>'

    # --------------------------------------------------------------------------
    # 状态卡片组（连接状态仪表板）
    # --------------------------------------------------------------------------

    @staticmethod
    def format_status_card(service_name: str, status: StatusLevel, detail: str = "") -> str:
        """渲染单个服务状态卡片。

        Args:
            service_name: 服务名称（如 "API"、"数据库"）
            status: StatusLevel 枚举值
            detail: 详细说明文字
        """
        color = status.color
        icon  = status.icon
        label = {
            StatusLevel.SUCCESS:  "连接正常",
            StatusLevel.WARNING:   "连接警告",
            StatusLevel.ERROR:     "连接失败",
            StatusLevel.INFO:      "检查中",
            StatusLevel.LOADING:   "检查中...",
        }.get(status, "未知")
        detail_html = (
            f'<div style="color:{color};font-size:.85em;margin-top:6px">{detail}</div>'
            if detail else ""
        )
        return (
            f'<div style="padding:14px 16px;border:1px solid {color};'
            f'border-radius:8px;text-align:center;flex:1;min-width:120px">'
            f'<div style="font-size:18px;margin-bottom:6px">{icon}</div>'
            f'<div style="font-weight:600;color:{color};font-size:.9em">{service_name.upper()}</div>'
            f'<div style="color:{color};font-size:.85em;margin-top:4px">{label}</div>'
            f'{detail_html}'
            f'</div>'
        )

    @staticmethod
    def format_status_dashboard(cards: list[str]) -> str:
        """渲染多个状态卡片的水平排列。"""
        return (
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin:12px 0">'
            + "".join(cards)
            + '</div>'
        )

    # --------------------------------------------------------------------------
    # Setup Wizard 进度条
    # --------------------------------------------------------------------------

    @staticmethod
    def format_setup_progress(steps: list[dict]) -> str:
        """渲染 Setup Wizard 进度指示器。

        Args:
            steps: [{"name": str, "done": bool, "active": bool}, ...]

        Example:
            >>> UXHelper.format_setup_progress([
            ...     {"name": "API配置",     "done": True,  "active": False},
            ...     {"name": "解密数据",     "done": False, "active": True},
            ...     {"name": "训练",        "done": False, "active": False},
            ... ])
        """
        icons = []
        for step in steps:
            if step["done"]:
                icons.append("✅")
            elif step["active"]:
                icons.append("🔄")
            else:
                icons.append("⬜")

        step_html = ""
        for i, step in enumerate(steps):
            icon  = icons[i]
            color = ("#65a88a" if step["done"] else "#fbbf24" if step["active"] else "#8c7b7f")
            label = step["name"]
            line  = (
                f'<div style="text-align:center;flex:1;padding:8px 4px">'
                f'<div style="font-size:18px;margin-bottom:4px">{icon}</div>'
                f'<div style="font-size:.8em;color:{color};font-weight:{"600" if step["done"] or step["active"] else "400"}>'
                f'{label}</div>'
                f'</div>'
            )
            if i > 0:
                line = (
                    f'<div style="flex:1;display:flex;align-items:center;padding:0 4px">'
                    f'<div style="flex:1;height:2px;background:{"#65a88a" if step["done"] else "#e0ddd8"}"></div>'
                    f'</div>' + line
                )
            step_html += line

        return (
            f'<div style="display:flex;align-items:center;gap:0;'
            f'margin:16px 0;padding:12px 16px;'
            f'background:#f7f7f5;border-radius:10px;border:1px solid #e6e3df">'
            + step_html +
            f'</div>'
        )

    # --------------------------------------------------------------------------
    # "思考中" 动画
    # --------------------------------------------------------------------------

    THINKING_HTML = (
        '<div id="thinking-indicator" style="'
        'display:flex;align-items:center;gap:8px;padding:6px 12px;'
        'color:#8c7b7f;font-size:.85em;margin-bottom:8px">'
        '<div style="display:flex;gap:3px">'
        '<div style="width:5px;height:5px;background:#a78bfa;border-radius:50%;'
        'animation:pulse 1.2s ease-in-out infinite"></div>'
        '<div style="width:5px;height:5px;background:#a78bfa;border-radius:50%;'
        'animation:pulse 1.2s ease-in-out .2s infinite"></div>'
        '<div style="width:5px;height:5px;background:#a78bfa;border-radius:50%;'
        'animation:pulse 1.2s ease-in-out .4s infinite"></div>'
        '</div>'
        '<span>正在理解你的消息...</span>'
        '<style>@keyframes pulse{0%,100%{opacity:.3;transform:scale(.8)}'
        '50%{opacity:1;transform:scale(1.2)}}</style>'
        '</div>'
    )

    @staticmethod
    def thinking_visible(visible: bool) -> str:
        """返回思考动画 HTML（visible=False 时返回空字符串）。"""
        if not visible:
            return ""
        return UXHelper.THINKING_HTML

    # --------------------------------------------------------------------------
    # 流式输出进度前缀（流式模式下在每个 chunk 前追加）
    # --------------------------------------------------------------------------

    @staticmethod
    def stream_progress_prompt(current: int, total: int) -> str:
        """流式输出时在首个 chunk 之前插入进度提示。"""
        pct = int(current / max(total, 1) * 100)
        return (
            f'<div style="font-size:.75em;color:#8c7b7f;padding:2px 0">'
            f'⏳ {pct}%'
            f'</div>'
        )

    # --------------------------------------------------------------------------
    # 流式分阶段进度指示器（新增）
    # --------------------------------------------------------------------------

    STREAM_STAGES = [
        ("thinking", "🤔 正在理解..."),
        ("retrieving", "🔍 检索记忆中..."),
        ("replying", "💬 正在回复..."),
    ]

    @staticmethod
    def stream_stage_html(stage: str, sub_text: str = "") -> str:
        """渲染单个分阶段状态指示器。

        Args:
            stage: "thinking" | "retrieving" | "replying"
            sub_text: 额外说明文字（如 "已检索 3 条"）
        """
        icon_map = {
            "thinking":   ("🤔", "#a78bfa"),
            "retrieving": ("🔍", "#fbbf24"),
            "replying":   ("💬", "#65a88a"),
        }
        label_map = {
            "thinking":   "正在理解你的消息",
            "retrieving": "检索相关记忆",
            "replying":   "生成回复中",
        }
        icon, color = icon_map.get(stage, ("⏳", "#8c7b7f"))
        label = label_map.get(stage, stage)
        sub_html = f'<div style="font-size:.78em;color:#8c7b7f;margin-top:2px">{sub_text}</div>' if sub_text else ""

        return (
            f'<div id="stream-stage-indicator" style="'
            'display:flex;align-items:center;gap:8px;padding:6px 12px;'
            'background:linear-gradient(90deg,#f7f7f5 0%,#f0ede8 100%);'
            'border-radius:8px;border:1px solid #e6dcd8;margin-bottom:8px">'
            f'<div style="font-size:14px;animation:pulse 1.4s ease-in-out infinite">{icon}</div>'
            f'<div style="flex:1">'
            f'<div style="font-size:.82em;color:{color};font-weight:500">{label}</div>'
            f'{sub_html}'
            '</div>'
            '<style>@keyframes pulse{0%,100%{opacity:.6;transform:scale(.9)}50%{opacity:1;transform:scale(1.1)}}</style>'
            '</div>'
        )

    @staticmethod
    def thinking_with_stage(stage: str, sub: str = "") -> str:
        """统一思考入口：stage 为空时返回原始动画，否则返回分阶段指示器。"""
        if not stage:
            return UXHelper.THINKING_HTML
        return UXHelper.stream_stage_html(stage, sub)

    # --------------------------------------------------------------------------
    # 重试进度 UI（新增）
    # --------------------------------------------------------------------------

    @staticmethod
    def retry_progress(current: int, total: int, operation: str = "重试中") -> str:
        """渲染重试进度条。

        Args:
            current: 当前重试次数（从 1 开始）
            total: 最大重试次数
            operation: 操作名称
        """
        pct = int(current / total * 100)
        color = "#65a88a" if pct == 100 else "#fbbf24"
        return (
            f'<div style="padding:8px 12px;background:#fef3c7;border-radius:6px;'
            'border:1px solid #fbbf24;margin:6px 0;font-size:.82em">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="animation:pulse 1s infinite">🔄</span>'
            f'<span style="color:#92400e">{operation}（{current}/{total}）</span>'
            f'</div>'
            f'<div style="margin-top:6px;height:4px;background:#e5e0d0;border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{color};border-radius:2px;transition:width .3s"></div>'
            f'</div>'
            '</div>'
        )

    @staticmethod
    def stream_chunk_prefix(stage: str, token_count: int = 0) -> str:
        """在流式回复的每个 chunk 前追加阶段标记（仅首个 chunk）。"""
        labels = {
            "thinking":   "🤔 理解中",
            "retrieving": "🔍 检索中",
            "replying":   "💬 回复中",
        }
        label = labels.get(stage, "")
        if token_count == 0:
            return f'<span style="font-size:.7em;color:#8c7b7f;margin-right:4px">{label} </span>'
        return ""

    # --------------------------------------------------------------------------
    # 训练进度条（用于 Setup Tab 训练过程中）
    # --------------------------------------------------------------------------

    @staticmethod
    def training_progress_html(
        step_name: str,
        current: int,
        total: int,
        detail: str = "",
    ) -> str:
        """渲染训练步骤进度条。

        Args:
            step_name: 步骤名称
            current: 当前进度（0-indexed）
            total: 总步骤数
            detail: 额外说明
        """
        pct = int(current / max(total, 1) * 100)
        color = "#65a88a" if pct >= 100 else "#a78bfa"
        detail_html = f'<div style="font-size:.78em;color:#8c7b7f;margin-top:2px">{detail}</div>' if detail else ""

        return (
            f'<div style="padding:10px 14px;background:#f7f5f3;border-radius:8px;'
            'border:1px solid #e6dcd8;margin:6px 0">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
            f'<span style="color:{color};font-size:.9em">{"✅" if pct >= 100 else "🔄"}</span>'
            f'<span style="font-weight:500;font-size:.85em;color:#3d2c30">{step_name}</span>'
            f'<span style="margin-left:auto;font-size:.75em;color:#8c7b7f">{current}/{total}</span>'
            f'</div>'
            f'<div style="height:4px;background:#e6dcd8;border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{color};border-radius:2px;transition:width .4s"></div>'
            f'</div>'
            f'{detail_html}'
            '</div>'
        )

    # --------------------------------------------------------------------------
    # 操作确认对话框（用于危险操作）
    # --------------------------------------------------------------------------

    @staticmethod
    def confirm_dialog(title: str, body: str, confirm_label: str = "确认", cancel_label: str = "取消") -> str:
        """渲染操作确认对话框 HTML（配合 Gradio 的 confirm component 或 JS dialog）。

        Returns HTML 片段，供嵌入到通知中。
        """
        onclick_confirm = "this.closest('[data-confirm]').remove()"
        onclick_cancel = "this.closest('[data-confirm]').remove()"
        return (
            '<div data-confirm style="padding:16px;background:#fef3c7;border-radius:8px;'
            'border:1px solid #fbbf24;margin:8px 0">'
            '<div style="font-weight:700;font-size:.9em;color:#92400e;margin-bottom:6px">&#26A0; '
            + title
            + '</div>'
            '<div style="font-size:.85em;color:#78350f;margin-bottom:12px;line-height:1.5">'
            + body
            + '</div>'
            '<div style="display:flex;gap:8px">'
            '<button onclick="'
            + onclick_confirm
            + '" style="padding:6px 14px;background:#fbbf24;color:white;border:none;border-radius:6px;cursor:pointer;font-size:.82em">'
            + confirm_label
            + '</button>'
            '<button onclick="'
            + onclick_cancel
            + '" style="padding:6px 14px;background:transparent;color:#92400e;border:1px solid #fbbf24;border-radius:6px;cursor:pointer;font-size:.82em">'
            + cancel_label
            + '</button>'
            '</div></div>'
        )
