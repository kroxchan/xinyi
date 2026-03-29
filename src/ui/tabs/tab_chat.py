"""Tab: tab_chat — extracted from app.py"""
from __future__ import annotations

import logging
from pathlib import Path

import gradio as gr

from src.features.cooldown import ConflictCooldownManager as _CCM
from src.ui.ux_helpers import UXHelper

_logger = logging.getLogger(__name__)


def render_chat_tab(components=None, is_ready=True, logger=None, blocks=None, demo=None):
    log = logger or _logger
    from src.engine.partner_advisor import (
        PartnerAdvisor,
        AdvisorSession,
        AdvisorSessionManager,
    )
    from src.engine.advisor_registry import get_registry as _get_registry
    from src.mediation.mediator import ConflictMediator

    _adv_mgr = AdvisorSessionManager()
    _adv_state = gr.State(value=None)  # current session id
    _last_twin_reply = gr.State(value=None)  # 最后一个分身回复，用于反馈检查

    def _init_advisor():
        if not components:
            return None
        from src.data.partner_config import load_twin_mode as _ltm_adv
        from openai import OpenAI as _AdvOAI
        api_cfg = components["config"]["api"]
        client = _AdvOAI(
            api_key=api_cfg.get("api_key", ""),
            base_url=api_cfg.get("base_url"),
            default_headers=api_cfg.get("headers", {}),
        )
        persona_path = Path(components["config"]["paths"]["persona_file"])
        persona_profile = {}
        if persona_path.exists():
            import yaml as _adv_yaml
            with open(persona_path, encoding="utf-8") as f:
                persona_profile = _adv_yaml.safe_load(f) or {}
        from src.personality.emotion_analyzer import EmotionAnalyzer as _AdvEA
        emo_path = components["config"]["paths"].get("emotion_file", "data/emotion_profile.yaml")
        emo_profile = _AdvEA.load(emo_path)
        tw = _ltm_adv()
        from src.personality.thinking_profiler import ThinkingProfiler as _AdvTP
        thinking_model = _AdvTP.load(
            components["config"]["paths"].get("thinking_model_file", "data/thinking_model.txt")
        )
        return PartnerAdvisor(
            api_client=client,
            model=api_cfg.get("model", "gpt-4o-mini"),
            conversation_builder=components["builder"],
            parser=components["parser"],
            cleaner=components["cleaner"],
            belief_graph=components["belief_graph"],
            memory_bank=components["memory_bank"],
            persona_profile=persona_profile,
            emotion_profile=emo_profile,
            twin_mode=tw,
            thinking_model=thinking_model,
        )

    # 注册到全局 registry，支持热重载
    _reg = _get_registry()
    _reg.register_advisor(_init_advisor)

    def _init_mediator():
        adv = _reg.get_advisor()
        if adv is None:
            return None
        return ConflictMediator(
            api_client=adv.client,
            model=adv.model,
            conversation_builder=adv.builder,
            parser=adv.parser,
            cleaner=adv.cleaner,
            belief_graph=adv.belief_graph,
            memory_bank=adv.memory_bank,
            persona_profile=adv.persona_profile,
            emotion_profile=adv.emotion_profile,
            twin_mode=adv.twin_mode,
            thinking_model=adv.thinking_model,
            kk_mode="short",
        )

    _reg.register_mediator(_init_mediator)

    def _get_advisor():
        return _reg.get_advisor()

    def _get_mediator():
        return _reg.get_mediator()

    # ================================================================
    # 冲突后冷却管理器 (ConflictCooldownManager)
    # ================================================================
    _cooldown_mgr = _CCM()

    def _render_cooldown_ui() -> str:
        """渲染冷却状态 HTML。"""
        if not _cooldown_mgr.is_in_cooldown():
            return ""

        remaining = _cooldown_mgr.get_remaining_hours()
        elapsed = _cooldown_mgr.get_elapsed_hours()

        if remaining <= 0:
            return ""

        if remaining >= 2:
            icon = "😔"
            title = "情绪冷却中"
            body = (
                "你们之间刚发生过一次高情绪对话。"
                "分身现在以更平静的语气回应你。"
                f"冷却还会持续 <b>{remaining:.1f}小时</b>。"
            )
            bar_color = "#f87171"
        else:
            icon = "🌱"
            title = "即将恢复"
            body = (
                f"冷却快结束了。"
                f"再过 <b>{remaining:.1f}小时</b> 分身语气会恢复正常。"
                "如果现在想说点什么，想想冷静后的自己会怎么说。"
            )
            bar_color = "#fbbf24"

        bar_width = max(5, int((elapsed / 24.0) * 100))

        return f"""<div style="
            background: linear-gradient(135deg, #2a2225 0%, #1e181b 100%);
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 12px;
            border: 1px solid {bar_color}30;
        ">
            <div style="display:flex;align-items:flex-start;gap:12px">
                <div style="font-size:24px">{icon}</div>
                <div style="flex:1">
                    <div style="font-size:13px;color:#d4c4c8;font-weight:600;margin-bottom:4px">
                        {title}
                    </div>
                    <div style="font-size:12px;color:#a8969a;line-height:1.6">
                        {body}
                    </div>
                    <div style="
                        margin-top:10px;height:3px;background:#3a3035;
                        border-radius:2px;overflow:hidden
                    ">
                        <div style="
                            width:{bar_width}%;height:100%;
                            background:{bar_color};border-radius:2px
                        "></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:4px">
                        <div style="font-size:10px;color:#5a4d50">
                            {elapsed:.1f}h 已过
                        </div>
                        <div style="font-size:10px;color:#5a4d50">
                            {remaining:.1f}h 剩余
                        </div>
                    </div>
                </div>
            </div>
        </div>"""

    from src.data.partner_config import load_twin_mode as _ltm_chat
    _chat_tw = _ltm_chat()
    _chat_desc = (
        "TA 的分身，用 TA 的语气跟你对话。"
        if _chat_tw == "partner"
        else "你的分身，用你的语气回应。"
    )
    gr.HTML(
        f'<div style="margin-bottom:12px">'
        f'<span style="font-size:.85em;color:#8c7b7f">{_chat_desc}</span>'
        f'</div>'
    )

    _CHAT_MAX_SESSION_SLOTS = 12
    gr.HTML(
        """
<style>
#sidebar-col.chat-sidebar-wrap {
  background: #f5f5f2;
  border-radius: 12px;
  padding: 10px 10px 12px 10px;
  border: 1px solid #e6e6e1;
  min-width: 260px !important;
  max-width: 320px !important;
  width: 280px !important;
  flex: 0 0 280px !important;
  box-sizing: border-box !important;
  overflow-x: hidden !important;
}
#sidebar-col.chat-sidebar-wrap > .form {
  width: 100% !important;
  max-width: 100% !important;
  box-sizing: border-box !important;
}
#sidebar-col .recents-label {
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #8a8580;
  margin: 4px 4px 8px 6px;
  font-weight: 600;
}
#sidebar-col .session-row-wrap {
  display: flex !important;
  flex-flow: row nowrap !important;
  align-items: stretch !important;
  gap: 4px !important;
  margin-bottom: 2px !important;
  width: 100% !important;
}
#sidebar-col .session-row-wrap > div {
  display: flex !important;
  flex-flow: row nowrap !important;
  align-items: stretch !important;
  min-width: 0 !important;
}
#sidebar-col .session-row-wrap > div:first-of-type {
  flex: 1 1 0% !important;
  min-width: 0 !important;
  max-width: calc(100% - 44px) !important;
}
#sidebar-col .session-row-wrap > div:last-of-type {
  flex: 0 0 40px !important;
  width: 40px !important;
  max-width: 40px !important;
  min-width: 40px !important;
}
#sidebar-col .session-row-wrap button.session-title-btn {
  font-size: 13px !important;
  line-height: 1.35 !important;
  min-height: 36px !important;
  max-height: 40px !important;
  width: 100% !important;
  max-width: 100% !important;
  justify-content: flex-start !important;
  text-align: left !important;
  padding: 6px 8px !important;
  border-radius: 8px !important;
  border: none !important;
  box-shadow: none !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
}
#sidebar-col .session-row-wrap button.session-title-btn.secondary {
  background: transparent !important;
  color: #2d2a26 !important;
}
#sidebar-col .session-row-wrap button.session-title-btn.primary {
  background: #ebe8e3 !important;
  color: #1a1816 !important;
  font-weight: 600 !important;
}
#sidebar-col .session-row-wrap button.session-del-btn {
  min-width: 36px !important;
  width: 100% !important;
  max-width: 40px !important;
  font-size: 15px !important;
  opacity: 0.45;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  flex-shrink: 0 !important;
  padding: 6px 4px !important;
}
#sidebar-col .session-row-wrap button.session-del-btn:hover {
  opacity: 1;
  background: #ebeae6 !important;
}
#sidebar-col.chat-sidebar-wrap #new-chat-btn {
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
  box-sizing: border-box !important;
  font-size: 13px !important;
  padding: 0 !important;
  border-radius: 10px !important;
  margin: 0 0 6px 0 !important;
}
#sidebar-col.chat-sidebar-wrap #new-chat-btn button {
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
  box-sizing: border-box !important;
  padding: 10px 12px !important;
  border-radius: 10px !important;
}
#chat-area.main-chat-panel {
  background: #fafaf8;
  border-radius: 12px;
  padding: 8px 8px 4px 8px;
  border: 1px solid #eceae6;
}
</style>
"""
    )

    with gr.Row():
        with gr.Column(scale=0, elem_id="sidebar-col", elem_classes=["chat-sidebar-wrap"]):
            adv_new_btn = gr.Button(
                "＋ 新对话", variant="primary", size="sm", elem_id="new-chat-btn"
            )
            gr.HTML('<div class="recents-label">最近对话</div>')
            _slot_title_btns = []
            _slot_del_btns = []
            for _slot_i in range(_CHAT_MAX_SESSION_SLOTS):
                with gr.Row(elem_classes=["session-row-wrap"]):
                    _tb = gr.Button(
                        "",
                        visible=False,
                        size="sm",
                        elem_classes=["session-title-btn"],
                        scale=5,
                    )
                    _db = gr.Button(
                        "🗑",
                        visible=False,
                        size="sm",
                        elem_classes=["session-del-btn"],
                        scale=0,
                        min_width=40,
                    )
                    _slot_title_btns.append(_tb)
                    _slot_del_btns.append(_db)
            _slot_outputs = []
            for _i in range(_CHAT_MAX_SESSION_SLOTS):
                _slot_outputs.append(_slot_title_btns[_i])
                _slot_outputs.append(_slot_del_btns[_i])

        with gr.Column(scale=3, elem_id="chat-area", elem_classes=["main-chat-panel"]):
            # 思考动画（在 chatbot 上方）
            thinking_indicator = gr.HTML(
                value="",
                elem_id="thinking-indicator",
            )
            chatbot = gr.Chatbot(
                height=520,
                type="messages",
                show_label=False,
                show_copy_button=True,
                elem_id="main-chatbot",
            )
            # 冷却状态显示区域
            cooldown_html = gr.HTML(
                value=_render_cooldown_ui(),
                elem_id="cooldown-status",
            )
            kk_mode_group = gr.Radio(
                choices=["💬 简短", "📖 详细"],
                value="💬 简短",
                label="KK 回复模式",
                show_label=True,
                elem_id="kk-mode-radio",
                info="简短：2-3句 · 详细：可以说更多",
            )
            with gr.Row():
                msg_input = gr.Textbox(
                    placeholder="跟TA聊聊…",
                    show_label=False, scale=8,
                    container=False, lines=1, max_lines=6,
                    elem_id="chat-input",
                )
                send_btn = gr.Button("↑", variant="primary", scale=0, min_width=46, elem_id="send-btn")
            gr.HTML(
                '<div style="font-size:12px;color:#888;padding:2px 8px 0">'
                '💡 在消息中任意位置加上 <b style="color:#a78bfa">@KK</b> '
                '即可召唤情感顾问，例如：<span style="color:#94a3b8">'
                '「@KK 我们最近老吵架怎么办」</span></div>'
            )

    def _adv_refresh_all(selected_id=None):
        """刷新侧栏会话槽：标题 + 行内删除，当前选中高亮。"""
        sessions = _adv_mgr.list_sessions()[:_CHAT_MAX_SESSION_SLOTS]
        out = []
        for i in range(_CHAT_MAX_SESSION_SLOTS):
            if i < len(sessions):
                raw = sessions[i]["title"] or "新对话"
                title = raw[:26] + "…" if len(raw) > 27 else raw
                sid = sessions[i]["id"]
                is_sel = selected_id and sid == selected_id
                out.append(
                    gr.update(
                        value=title,
                        visible=True,
                        variant="primary" if is_sel else "secondary",
                    )
                )
                out.append(gr.update(visible=True))
            else:
                out.append(gr.update(visible=False, value=""))
                out.append(gr.update(visible=False))
        return tuple(out)

    def _adv_session_to_chatbot(session):
        if session is None:
            return []
        result = []
        for m in session.messages:
            content = m["content"]
            if m["role"] == "assistant" and content.startswith("【KK】"):
                result.append({"role": "assistant",
                               "content": f"💜 **KK**：{content[4:].strip()}"})
            else:
                result.append({"role": m["role"], "content": content})
        return result

    def _adv_new_session():
        s = _adv_mgr.create()
        return (s.id, [],) + _adv_refresh_all(s.id)

    def _adv_open_slot(slot_index: int):
        def _fn():
            sessions = _adv_mgr.list_sessions()[:_CHAT_MAX_SESSION_SLOTS]
            if slot_index >= len(sessions):
                return (None, [],) + _adv_refresh_all(None)
            sid = sessions[slot_index]["id"]
            s = _adv_mgr.load(sid)
            if s is None:
                return (None, [],) + _adv_refresh_all(None)
            return (sid, _adv_session_to_chatbot(s)) + _adv_refresh_all(sid)

        return _fn

    def _adv_del_slot(slot_index: int):
        def _fn(current_sid):
            sessions = _adv_mgr.list_sessions()[:_CHAT_MAX_SESSION_SLOTS]
            if slot_index >= len(sessions):
                s = _adv_mgr.load(current_sid) if current_sid else None
                chat = _adv_session_to_chatbot(s) if s else []
                return (current_sid, chat,) + _adv_refresh_all(current_sid)
            sid = sessions[slot_index]["id"]
            _adv_mgr.delete(sid)
            if current_sid == sid:
                return (None, [],) + _adv_refresh_all(None)
            s = _adv_mgr.load(current_sid) if current_sid else None
            chat = _adv_session_to_chatbot(s) if s else []
            return (current_sid, chat,) + _adv_refresh_all(current_sid)

        return _fn

    def _adv_send(user_msg, session_id, chatbot_history, kk_mode="💬 简短"):
        if not user_msg or not user_msg.strip():
            return (
                "",
                chatbot_history,
                session_id,
                gr.update(),
                gr.update(),
                _render_cooldown_ui(),
            ) + _adv_refresh_all(session_id)

        is_xiaoan = "@KK" in user_msg

        new_twin_reply = gr.update()

        if not session_id:
            s = _adv_mgr.create()
            session_id = s.id
        else:
            s = _adv_mgr.load(session_id)
            if s is None:
                s = _adv_mgr.create()
                session_id = s.id

        if is_xiaoan:
            mediator = _get_mediator()
            if mediator is None:
                chatbot_history = chatbot_history or []
                chatbot_history.append({"role": "assistant",
                                        "content": "💜 **KK**：系统未初始化，请先完成学习。"})
                return (
                    "",
                    chatbot_history,
                    session_id,
                    gr.update(),
                    gr.update(),
                    _render_cooldown_ui(),
                ) + _adv_refresh_all(session_id)

            mode = "detailed" if kk_mode == "📖 详细" else "short"
            mediator.set_kk_mode(mode)

            clean_msg = user_msg.replace("@KK", "").strip() or user_msg.strip()
            s.add_message("user", user_msg.strip())

            mediator._ready.wait(timeout=120)
            system = mediator._system_prompt or "你是 KK，心译的关系洞察顾问。"

            history = []
            for m in s.messages[:-1]:
                c = m["content"]
                if m["role"] == "assistant" and c.startswith("【KK】"):
                    history.append({"role": "assistant",
                                    "content": c[4:].strip()})
                elif m["role"] == "assistant":
                    history.append({"role": "user",
                                    "content": f"（对象分身回复了：{c}）"})
                else:
                    history.append({"role": "user",
                                    "content": c.replace("@KK", "").strip()})
            history.append({"role": "user", "content": clean_msg})

            api_messages = [{"role": "system", "content": system}]
            api_messages.extend(history)

            try:
                resp = mediator.client.chat.completions.create(
                    model=mediator.model,
                    messages=api_messages,
                    temperature=0.85,
                    max_tokens=500,
                )
                reply = (resp.choices[0].message.content or "").strip()
            except Exception as e:
                log.exception("Mediator LLM call failed")
                reply = f"不好意思，出了点问题（{e}）"

            s.add_message("assistant", f"【KK】{reply}")
        else:
            advisor = _get_advisor()
            if advisor is None:
                chatbot_history = chatbot_history or []
                chatbot_history.append({"role": "assistant",
                                        "content": "系统未初始化，请先完成训练。"})
                return (
                    "",
                    chatbot_history,
                    session_id,
                    gr.update(),
                    gr.update(),
                    _render_cooldown_ui(),
                ) + _adv_refresh_all(session_id)

            # 显示思考动画
            yield "", chatbot_history, session_id, gr.update(), UXHelper.thinking_visible(True), _render_cooldown_ui()
            _chat_history = chatbot_history or []

            cooldown_prompt = _cooldown_mgr.get_cooldown_prompt()
            bubbles = advisor.chat(user_msg.strip(), s, cooldown_prompt=cooldown_prompt)

            # 检查情绪状态，触发冷却（如需要）
            if hasattr(advisor, 'emotion_tracker') and advisor.emotion_tracker:
                emo = advisor.emotion_tracker.current_emotion
                conf = advisor.emotion_tracker.confidence
                triggered = _cooldown_mgr.check_and_trigger(emo, conf)
                if triggered:
                    ui_msg = _cooldown_mgr.get_ui_message()
                    if ui_msg:
                        s.add_message("assistant", f"💭 *{ui_msg}*")

            if bubbles:
                new_twin_reply = "\n".join(bubbles)

        s.auto_title()
        _adv_mgr.save(s)

        cooldown_html_value = _render_cooldown_ui()
        yield (
            "",
            _adv_session_to_chatbot(s),
            session_id,
            new_twin_reply,
            UXHelper.thinking_visible(False),
            cooldown_html_value,
        ) + _adv_refresh_all(session_id)

    def _adv_send_stream(user_msg, session_id, chatbot_history, kk_mode="💬 简短"):
        """流式版本的 _adv_send：yield 每个回复 chunk，实时更新 UI。"""
        # 先执行所有预检查和初始化（与原版相同）
        if not user_msg or not user_msg.strip():
            yield (
                "",
                chatbot_history,
                session_id,
                gr.update(),
                gr.update(),
                _render_cooldown_ui(),
            ) + _adv_refresh_all(session_id)
            return

        is_xiaoan = "@KK" in user_msg

        if not session_id:
            s = _adv_mgr.create()
            session_id = s.id
        else:
            s = _adv_mgr.load(session_id)
            if s is None:
                s = _adv_mgr.create()
                session_id = s.id

        if is_xiaoan:
            # KK 模式暂不使用流式（单次请求，结果简短）
            mediator = _get_mediator()
            if mediator is None:
                _hist = chatbot_history or []
                _hist.append({"role": "assistant",
                              "content": "💜 **KK**：系统未初始化，请先完成学习。"})
                yield (
                    "",
                    _hist,
                    session_id,
                    gr.update(),
                    gr.update(),
                    _render_cooldown_ui(),
                ) + _adv_refresh_all(session_id)
                return

            mode = "detailed" if kk_mode == "📖 详细" else "short"
            mediator.set_kk_mode(mode)
            clean_msg = user_msg.replace("@KK", "").strip() or user_msg.strip()
            s.add_message("user", user_msg.strip())
            mediator._ready.wait(timeout=120)
            system = mediator._system_prompt or "你是 KK，心译的关系洞察顾问。"
            history = []
            for m in s.messages[:-1]:
                c = m["content"]
                if m["role"] == "assistant" and c.startswith("【KK】"):
                    history.append({"role": "assistant", "content": c[4:].strip()})
                elif m["role"] == "assistant":
                    history.append({"role": "user", "content": f"（对象分身回复了：{c}）"})
                else:
                    history.append({"role": "user", "content": c.replace("@KK", "").strip()})
            history.append({"role": "user", "content": clean_msg})
            api_messages = [{"role": "system", "content": system}]
            api_messages.extend(history)

            try:
                resp = mediator.client.chat.completions.create(
                    model=mediator.model,
                    messages=api_messages,
                    temperature=0.85,
                    max_tokens=500,
                )
                reply = (resp.choices[0].message.content or "").strip()
            except Exception as e:
                log.exception("Mediator LLM call failed")
                reply = UXHelper.format_error(
                    title="KK 回复失败",
                    message=str(e)[:80],
                    solution="请稍后重试，或检查 API 配置。",
                )

            s.add_message("assistant", f"【KK】{reply.strip()}")
            s.auto_title()
            _adv_mgr.save(s)
            yield (
                "",
                _adv_session_to_chatbot(s),
                session_id,
                gr.update(),
                UXHelper.thinking_visible(False),
                _render_cooldown_ui(),
            ) + _adv_refresh_all(session_id)
            return

        # 普通分身对话模式：使用真正的流式 API
        advisor = _get_advisor()
        if advisor is None:
            _hist = chatbot_history or []
            _hist.append({"role": "assistant", "content": "系统未初始化，请先完成训练。"})
            yield (
                "",
                _hist,
                session_id,
                gr.update(),
                gr.update(),
                _render_cooldown_ui(),
            ) + _adv_refresh_all(session_id)
            return

        _hist = chatbot_history or []
        # 先显示思考动画
        yield "", _hist, session_id, gr.update(), UXHelper.thinking_visible(True), _render_cooldown_ui()

        # emotion tracker 同步更新（不阻塞太快）
        try:
            advisor._ready.wait(timeout=5)
        except Exception:
            pass

        # 写 user message（供 history window 使用）
        s.add_message("user", user_msg.strip())
        accumulated = ""
        stage_shown = False

        try:
            for chunk in advisor.chat_stream(user_msg.strip(), s):
                accumulated += chunk
                if not stage_shown:
                    # 第一个 chunk 到达 → 切换为 "回复中" 阶段
                    yield "", _hist, session_id, gr.update(), UXHelper.thinking_visible(False), _render_cooldown_ui()
                    stage_shown = True
                # 实时追加到 textbox（用户可看到逐字输出）
                yield "", _hist, session_id, gr.update(), gr.update(), _render_cooldown_ui()
        except Exception as e:
            log.exception("Stream generator failed")
            accumulated = UXHelper.format_error(
                title="回复生成失败",
                message=str(e)[:120],
                solution="请稍后重试。",
            )
            stage_shown = True

        # 冷却检查（仅在流式完成后）
        if hasattr(advisor, 'emotion_tracker') and advisor.emotion_tracker:
            emo = advisor.emotion_tracker.current_emotion
            conf = advisor.emotion_tracker.confidence
            triggered = _cooldown_mgr.check_and_trigger(emo, conf)
            if triggered:
                ui_msg = _cooldown_mgr.get_cooldown_prompt()
                if ui_msg:
                    s.add_message("assistant", f"💭 *{ui_msg}*")

        # 分割气泡并写入 session
        if accumulated:
            bubbles = [ln.strip() for ln in accumulated.split("\n") if ln.strip()]
            if not bubbles:
                bubbles = [accumulated]
            for b in bubbles:
                s.add_message("assistant", b)
            new_twin_reply = "\n".join(bubbles)
        else:
            new_twin_reply = ""

        s.auto_title()
        _adv_mgr.save(s)

        yield (
            "",
            _adv_session_to_chatbot(s),
            session_id,
            new_twin_reply,
            UXHelper.thinking_visible(False),
            _render_cooldown_ui(),
        ) + _adv_refresh_all(session_id)

    adv_new_btn.click(
        fn=_adv_new_session,
        outputs=[_adv_state, chatbot] + _slot_outputs,
    )
    # 流式发送：实时显示思考动画 + 流式回复
    # outputs 增加 thinking_indicator（gr.HTML 组件）
    send_btn.click(
        fn=_adv_send_stream,
        inputs=[msg_input, _adv_state, chatbot, kk_mode_group],
        outputs=[msg_input, chatbot, _adv_state, _last_twin_reply, thinking_indicator, cooldown_html]
        + _slot_outputs,
    )
    msg_input.submit(
        fn=_adv_send_stream,
        inputs=[msg_input, _adv_state, chatbot, kk_mode_group],
        outputs=[msg_input, chatbot, _adv_state, _last_twin_reply, thinking_indicator, cooldown_html]
        + _slot_outputs,
    )
    for _si in range(_CHAT_MAX_SESSION_SLOTS):
        _slot_title_btns[_si].click(
            fn=_adv_open_slot(_si),
            outputs=[_adv_state, chatbot] + _slot_outputs,
        )
        _slot_del_btns[_si].click(
            fn=_adv_del_slot(_si),
            inputs=[_adv_state],
            outputs=[_adv_state, chatbot] + _slot_outputs,
        )
    if blocks is not None:
        blocks.load(
            fn=lambda: _adv_refresh_all(None),
            outputs=_slot_outputs,
        )

    # ================================================================
    # 「不像 TA」即时反馈区
    # ================================================================
    from src.features.feedback import AuthenticityChecker as _AC
    from src.data.partner_config import load_partner_wxid as _lpwxid

    _checker_inst = [None]

    def _init_checker():
        adv = _get_advisor()
        if adv is None or components is None:
            return None
        from src.memory.vector_store import VectorStore as _VS
        from src.memory.embedder import TextEmbedder as _TE
        try:
            vector_store = _VS(
                persist_dir="data/chroma_db",
                collection_name="conversations",
            )
            embedder = _TE()
        except Exception:
            vector_store = None
            embedder = None
        return _AC(
            api_client=adv.client,
            vector_store=vector_store,
            persona_profile=adv.persona_profile,
            emotion_profile=adv.emotion_profile,
            embedder=embedder,
            model=adv.model,
        )

    def _get_checker():
        if _checker_inst[0] is None:
            _checker_inst[0] = _init_checker()
        return _checker_inst[0]

    def _format_feedback_result(result: dict) -> str:
        """将反馈检查结果格式化为可读文本。"""
        if result.get("insufficient_data"):
            return (
                "📊 **数据不足，难以准确判断**\n\n"
                f"当前对话库仅有少量数据，{result.get('retrain_suggestion', '建议继续训练更多对话。')}"
            )

        score = result.get("authenticity_score", 0.5)
        score_pct = int(score * 100)
        score_bar = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)
        score_emoji = "😊" if score >= 0.7 else "😐" if score >= 0.4 else "😕"
        score_label = "很像" if score >= 0.7 else "一般" if score >= 0.4 else "不太像"

        deviation = result.get("deviation_notes", "暂无分析")
        examples = result.get("real_examples", [])
        suggestion = result.get("retrain_suggestion", "")

        html = f"""<div style="
            background: linear-gradient(135deg, #2a2225 0%, #1e181b 100%);
            border-radius: 14px;
            padding: 18px 20px;
            margin-top: 16px;
            border: 1px solid #3a3035;
        ">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
                <span style="font-size:20px">{score_emoji}</span>
                <div style="flex:1">
                    <div style="font-size:12px;color:#a8969a;margin-bottom:4px">
                        真实性评分 {score_label}
                    </div>
                    <div style="display:flex;align-items:center;gap:8px">
                        <span style="font-family:monospace;color:#65a88a;font-weight:600">{score_bar}</span>
                        <span style="font-size:13px;color:#65a88a;font-weight:700">{score_pct}%</span>
                    </div>
                </div>
            </div>

            <div style="background:#1e181b;border-radius:8px;padding:12px 14px;margin-bottom:12px">
                <div style="font-size:11px;color:#7a6b6f;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
                    分析
                </div>
                <div style="font-size:13px;color:#d4c4c8;line-height:1.6">
                    {deviation}
                </div>
            </div>
        """

        if examples:
            examples_html = ""
            for i, ex in enumerate(examples[:2], 1):
                ex_short = ex[:120] + "…" if len(ex) > 120 else ex
                examples_html += f"""<div style="
                    background:#1e181b;border-radius:8px;padding:10px 12px;
                    margin-bottom:8px;border-left:3px solid #65a88a40
                ">
                    <div style="font-size:10px;color:#5a4d50;margin-bottom:4px">
                        真实片段 {i}
                    </div>
                    <div style="font-size:12px;color:#a8969a;line-height:1.5">
                        {ex_short}
                    </div>
                </div>"""
            html += f"""<div style="margin-bottom:12px">
                <div style="font-size:11px;color:#7a6b6f;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">
                    参考
                </div>
                {examples_html}
            </div>"""

        if suggestion:
            html += f"""<div style="
                background: linear-gradient(135deg, #2a2520 0%, #1e1a18 100%);
                border-radius:8px;padding:12px 14px;
                border: 1px solid #fbbf2430;
            ">
                <div style="font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
                    建议
                </div>
                <div style="font-size:13px;color:#d4c4c8;line-height:1.5">
                    {suggestion}
                </div>
            </div>"""

        html += "</div>"
        return html

    def _check_feedback(twin_reply: str):
        if not twin_reply or not twin_reply.strip():
            return (
                '<div style="padding:16px;color:#a8969a;font-size:13px">'
                '还没有分身回复可以检查～'
                '</div>',
                gr.update(),
            )

        checker = _get_checker()
        if checker is None:
            return (
                '<div style="padding:16px;color:#f87171;font-size:13px">'
                '⚠️ 系统未初始化，请先完成学习。'
                '</div>',
                gr.update(),
            )

        try:
            contact_wxid = _lpwxid() or None
            result = checker.check(twin_reply.strip(), contact_wxid)
            formatted = _format_feedback_result(result)
            retrain_btn = (
                '<button style="'
                'margin-top:12px;padding:10px 16px;background:#a78bfa;'
                'color:white;border:none;border-radius:8px;font-size:13px;'
                'cursor:pointer;width:100%" '
                'onclick="window.location.hash=\'#/setup\'"'
                '>再喂 5 条对话给 TA →</button>'
            )
            if not result.get("insufficient_data"):
                formatted = formatted.replace("</div>", retrain_btn + "</div>", 1)
            return formatted, twin_reply
        except Exception as e:
            log.exception("Feedback check failed")
            return (
                f'<div style="padding:16px;color:#f87171;font-size:13px">'
                f'检查失败，请稍后重试。（{str(e)[:50]}）'
                f'</div>',
                gr.update(),
            )

    with gr.Accordion("👎 不像 TA？检查一下", open=False, elem_id="feedback-accordion"):
        gr.HTML(
            '<div style="font-size:12px;color:#8c7b7f;margin-bottom:12px">'
            '对比真实对话，分析这条回复哪里不像TA。'
            '</div>'
        )
        with gr.Row():
            feedback_check_btn = gr.Button(
                "🔍 检查上一条回复",
                variant="secondary",
                size="sm",
                elem_id="feedback-check-btn",
            )
            feedback_clear_btn = gr.Button(
                "清除",
                variant="secondary",
                size="sm",
            )
        feedback_result = gr.HTML(
            value=(
                '<div style="padding:16px;color:#8c7b7f;font-size:13px;text-align:center">'
                '点击按钮检查上一条分身回复'
                '</div>'
            ),
            elem_id="feedback-result",
        )

    feedback_check_btn.click(
        fn=_check_feedback,
        inputs=_last_twin_reply,
        outputs=[feedback_result, _last_twin_reply],
    )

    feedback_clear_btn.click(
        fn=lambda: (
            '<div style="padding:16px;color:#8c7b7f;font-size:13px;text-align:center">'
            '点击按钮检查上一条分身回复'
            '</div>',
            None,
        ),
        outputs=[feedback_result, _last_twin_reply],
    )

    # ================================================================
    # 发前对齐 MVP
    # ================================================================
    from src.features.pre_send import PreSendAligner as _PSA

    _aligner_inst = [None]

    def _init_aligner():
        adv = _get_advisor()
        if adv is None:
            return None
        return _PSA(
            api_client=adv.client,
            partner_advisor_instance=adv,
            model=adv.model,
        )

    def _get_aligner():
        if _aligner_inst[0] is None:
            _aligner_inst[0] = _init_aligner()
        return _aligner_inst[0]

    gr.HTML(
        '<div style="margin-top:24px;margin-bottom:8px">'
        '<span style="font-size:.85em;color:#a78bfa;font-weight:500">'
        '💭 发前对齐 — 发送前先「对齐」一下理解'
        '</span></div>'
    )
    gr.HTML(
        '<div style="font-size:12px;color:#888;margin-bottom:12px">'
        '粘贴你想说的话，看看对方可能会怎么理解。'
        '</div>'
    )

    with gr.Row(elem_id="align-input-row"):
        draft_input = gr.Textbox(
            placeholder="粘贴你想说的话…",
            lines=3,
            scale=8,
            show_label=False,
            elem_id="draft-input",
        )
        align_btn = gr.Button(
            "🤔 对齐一下",
            variant="secondary",
            scale=0,
            min_width=100,
            elem_id="align-btn",
        )

    with gr.Column(elem_id="align-result-area"):
        align_output = gr.Textbox(
            label="对齐结果",
            lines=6,
            show_label=True,
            interactive=False,
            elem_id="align-output",
        )

    def _format_align_result(result: dict) -> str:
        """将对齐结果格式化为可读文本。"""
        lines = []

        how_they_hear = result.get("how_they_hear", "")
        if how_they_hear:
            lines.append(f"**TA 可能听到的版本**\n{how_they_hear}")

        emotion = result.get("their_emotion", "")
        if emotion:
            lines.append(f"**TA 可能触发的情绪**：{emotion}")

        tip = result.get("one_tip", "")
        if tip:
            lines.append(f"**一句话建议**：{tip}")

        rewrites = result.get("rewrites", [])
        if rewrites:
            rw_lines = []
            for i, rw in enumerate(rewrites, 1):
                if rw:
                    rw_lines.append(f"{i}. {rw}")
            if rw_lines:
                lines.append(f"**可选改写**\n" + "\n".join(rw_lines))

        return "\n\n".join(lines) if lines else "（未能生成结果，请稍后重试）"

    def _do_align(draft: str):
        if not draft or not draft.strip():
            return "请先输入你想说的话～"

        aligner = _get_aligner()
        if aligner is None:
            return "⚠️ 系统未初始化，请先完成学习。"

        try:
            result = aligner.align(draft)
            return _format_align_result(result)
        except ValueError as e:
            return f"提示：{e}"
        except RuntimeError as e:
            return f"出错了：{e}"
        except Exception as e:
            log.exception("PreSendAligner error")
            return f"不好意思出了点问题，请稍后重试（{e}）"

    align_btn.click(
        fn=_do_align,
        inputs=draft_input,
        outputs=align_output,
    )

    return None, chatbot, _adv_state, thinking_indicator


# 兼容旧名称
render_tab_chat = render_chat_tab
