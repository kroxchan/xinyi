"""FTUE: First-Time User Experience — Dual Mode Explainer."""

from __future__ import annotations


def get_dual_mode_comparison_html(highlight_mode: str = "self") -> str:
    """返回并排对比 HTML，highlight_mode 用于高亮当前选中项。"""
    self_border = "2px solid #a78bfa" if highlight_mode == "self" else "2px solid transparent"
    partner_border = "2px solid #a78bfa" if highlight_mode == "partner" else "2px solid transparent"

    return f"""
    <div style="
        background: linear-gradient(135deg, #2a2225 0%, #1e181b 100%);
        border-radius: 16px;
        padding: 24px;
        border: 1px solid #3a3035;
        margin-bottom: 20px;
    ">
        <div style="text-align:center;margin-bottom:20px">
            <div style="font-size:15px;color:#d4c4c8;font-weight:500;margin-bottom:4px">
                你想先练习什么？
            </div>
            <div style="font-size:12px;color:#8c7b7f">
                选错了可以随时切换，不影响已学习的数据
            </div>
            <div style="font-size:11px;color:#a8969a;margin-top:10px">
                本区域为两种模式的<strong style="color:#d4c4c8">说明对照</strong>（不可点选）；请在说明区<strong style="color:#d4c4c8">下方</strong>使用大按钮切换当前模式
            </div>
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap">
            <!-- 练自己卡片 -->
            <div style="
                flex:1;min-width:200px;background:#252030;border-radius:12px;padding:18px;
                border:{self_border};cursor:default;
                transition:border-color 0.2s ease;
            ">
                <div style="text-align:center;margin-bottom:12px">
                    <div style="font-size:24px;margin-bottom:6px">🪞</div>
                    <div style="font-size:15px;color:#d4c4c8;font-weight:600">练自己</div>
                    <div style="font-size:12px;color:#a78bfa;margin-top:2px">认识自己的说话风格</div>
                </div>
                <div style="font-size:12px;color:#a8969a;line-height:1.8">
                    <strong style="color:#c4b4b8">适合：</strong>想提升表达能力<br/>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;复盘自己的沟通模式<br/>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;想知道自己怎么说话<br/>
                    <br/>
                    <strong style="color:#c4b4b8">场景：</strong>你跟自己对话<br/>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;「我下次可以怎么说」
                </div>
                <div style="text-align:center;margin-top:12px">
                    <span style="font-size:20px">💭</span>
                    <div style="font-size:11px;color:#8c7b7f;margin-top:4px">就像照镜子</div>
                </div>
            </div>
            <!-- 练对象卡片 -->
            <div style="
                flex:1;min-width:200px;background:#252030;border-radius:12px;padding:18px;
                border:{partner_border};cursor:default;
                transition:border-color 0.2s ease;
            ">
                <div style="text-align:center;margin-bottom:12px">
                    <div style="font-size:24px;margin-bottom:6px">👓</div>
                    <div style="font-size:15px;color:#d4c4c8;font-weight:600">练对象</div>
                    <div style="font-size:12px;color:#a78bfa;margin-top:2px">理解对方的思考方式</div>
                </div>
                <div style="font-size:12px;color:#a8969a;line-height:1.8">
                    <strong style="color:#c4b4b8">适合：</strong>想减少沟通误会<br/>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;理解对方为什么那样说<br/>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;预测对方可能的反应<br/>
                    <br/>
                    <strong style="color:#c4b4b8">场景：</strong>跟对方对话（模拟）<br/>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;「他/她会怎么理解」
                </div>
                <div style="text-align:center;margin-top:12px">
                    <span style="font-size:20px">🔮</span>
                    <div style="font-size:11px;color:#8c7b7f;margin-top:4px">就像戴对方的眼镜</div>
                </div>
            </div>
        </div>
        <div style="text-align:center;margin-top:16px;font-size:12px;color:#8c7b7f">
            💡 选错了？随时可以在「设置」里切换，两个模式的数据互不影响
        </div>
    </div>
    """


def get_mode_switch_confirm_html(mode: str) -> str:
    """返回模式切换确认 toast HTML。"""
    label = "🪞 练自己" if mode == "self" else "👓 练对象"
    return f"""
    <div style="
        padding:10px 14px;
        background:#2a2520;
        border-radius:8px;
        border:1px solid #a78bfa40;
        font-size:13px;
        color:#d4c4c8;
        text-align:center;
        margin-top:12px;
        animation:fadeIn 0.3s ease;
    ">
        已切换到【{label}】模式。可以开始对话了！
    </div>
    <style>
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(-5px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
    </style>
    """


class DualModeExplainer:
    """FTUE 并排模式说明组件。"""

    def __init__(self, current_mode: str = "self"):
        self.current_mode = current_mode if current_mode in ("self", "partner") else "self"

    def render_html(self) -> str:
        """返回带选中状态的 HTML。"""
        return get_dual_mode_comparison_html(highlight_mode=self.current_mode)

    def render_confirm(self, mode: str) -> str:
        """返回模式切换确认 HTML。"""
        return get_mode_switch_confirm_html(mode)

    def switch_mode(self, mode: str) -> tuple[str, str]:
        """切换模式并返回新的 HTML 和确认信息。"""
        self.current_mode = mode if mode in ("self", "partner") else "self"
        return self.render_html(), self.render_confirm(self.current_mode)
