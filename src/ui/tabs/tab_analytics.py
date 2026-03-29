"""Tab: tab_analytics — extracted from app.py"""
from __future__ import annotations

import logging
from pathlib import Path

import gradio as gr

logger = logging.getLogger(__name__)


def _lazy(name: str):
    import src.app as _m
    return getattr(_m, name)


def _init_shareable_generator(components):
    """Initialize the ShareableReportGenerator from components."""
    if not components:
        return None
    try:
        from openai import OpenAI
        from src.personality.emotion_analyzer import EmotionAnalyzer
        from src.personality.thinking_profiler import ThinkingProfiler
        from src.features.shareable_report import ShareableReportGenerator

        api_cfg = components["config"]["api"]
        client = OpenAI(
            api_key=api_cfg.get("api_key", ""),
            base_url=api_cfg.get("base_url"),
            default_headers=api_cfg.get("headers", {}),
        )

        persona_path = Path(components["config"]["paths"]["persona_file"])
        persona_profile = {}
        if persona_path.exists():
            import yaml
            with open(persona_path, encoding="utf-8") as f:
                persona_profile = yaml.safe_load(f) or {}

        emo_path = components["config"]["paths"].get("emotion_file", "data/emotion_profile.yaml")
        emotion_profile = EmotionAnalyzer.load(emo_path)

        thinking_model = ThinkingProfiler.load(
            components["config"]["paths"].get("thinking_model_file", "data/thinking_model.txt")
        )

        return ShareableReportGenerator(
            api_client=client,
            model=api_cfg.get("model", "gpt-4o-mini"),
            persona_profile=persona_profile,
            emotion_profile=emotion_profile,
            belief_graph=components["belief_graph"],
            memory_bank=components["memory_bank"],
        )
    except Exception as e:
        logger.warning("Failed to init shareable generator: %s", e)
        return None


def render_tab_analytics(components=None, demo=None):
    load_analytics = _lazy("load_analytics")
    refresh_analytics_btn = gr.Button("刷新分析", variant="secondary")

    overview_html = gr.HTML(label="数据概览")

    with gr.Row():
        with gr.Column(scale=1):
            contacts_html = gr.HTML()
        with gr.Column(scale=1):
            hourly_html = gr.HTML()

    monthly_html = gr.HTML()

    with gr.Row():
        with gr.Column(scale=1):
            relationship_html = gr.HTML()
        with gr.Column(scale=1):
            belief_summary_html = gr.HTML()

    persona_html = gr.HTML()

    analytics_outputs = [overview_html, contacts_html, hourly_html, monthly_html, relationship_html, belief_summary_html, persona_html]
    refresh_analytics_btn.click(fn=load_analytics, outputs=analytics_outputs)
    if demo is not None:
        demo.load(fn=load_analytics, outputs=analytics_outputs)

    # ================================================================
    # 单方视角可分享报告
    # ================================================================
    gr.HTML('<div style="margin-top:24px"></div>')
    gr.HTML(
        '<span style="font-size:.9em;color:#a78bfa;font-weight:500">'
        '📄 可分享报告 — 只关于「我」的那部分'
        '</span>'
    )
    gr.HTML(
        '<div style="font-size:12px;color:#888;margin-bottom:10px">'
        '生成一份只关于你自己的沟通画像，方便存档或对外分享。'
        '</div>'
    )

    perspective_radio = gr.Radio(
        choices=["我的沟通画像", "TA的沟通画像"],
        value="我的沟通画像",
        label=None,
        show_label=False,
        elem_id="shareable-perspective-radio",
    )
    shareable_generate_btn = gr.Button("生成报告", variant="secondary", size="sm")

    # Initialize generator lazily (before event wiring)
    _shareable_gen = [_init_shareable_generator(components) if components else None]

    def _get_shareable_gen():
        if _shareable_gen[0] is None and components:
            _shareable_gen[0] = _init_shareable_generator(components)
        return _shareable_gen[0]

    def _generate_shareable_report(choice_label):
        gen = _get_shareable_gen()
        if gen is None:
            return "⚠️ 系统未初始化，请先完成学习。"

        perspective = "partner" if "TA" in choice_label else "self"
        try:
            result = gen.generate(perspective=perspective)
            return result.get("raw_text", result.get("shareable_text", "（生成失败）"))
        except Exception as e:
            logger.exception("Shareable report generation failed")
            return f"不好意思出了点问题，请稍后重试。（{str(e)[:50]}）"

    shareable_output = gr.Textbox(
        label="单方视角报告",
        lines=14,
        interactive=False,
        elem_id="shareable-report-output",
    )
    with gr.Row():
        copy_report_btn = gr.Button("📋 复制报告", variant="secondary", size="sm")
        copy_result = gr.HTML(value='<span id="copy-result" style="font-size:12px;color:#65a88a"></span>')
    gr.HTML(
        '<div style="font-size:12px;color:#888;margin-top:4px">'
        '这份报告只包含关于「你」的分析，不含对方数据，可安全分享。'
        '</div>'
    )

    def _copy_report(text):
        if not text or not text.strip():
            return '<span style="font-size:12px;color:#888">报告为空</span>'
        return '<span style="font-size:12px;color:#65a88a">✅ 已准备好内容，请在输入框中复制</span>'

    shareable_generate_btn.click(
        fn=_generate_shareable_report,
        inputs=perspective_radio,
        outputs=shareable_output,
    )

    copy_report_btn.click(
        fn=_copy_report,
        inputs=shareable_output,
        outputs=copy_result,
    )

    # ================================================================
    # Tab: Belief Graph
    # ================================================================
