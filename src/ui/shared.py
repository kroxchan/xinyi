"""Shared UI helpers — extracted from app.py.

These functions are used across multiple Tabs and should be imported
from this module rather than duplicated.
"""
from __future__ import annotations

import gradio as gr
from pathlib import Path
import yaml


# ==============================================================================
# Global state accessors (will be set at runtime from app.py)
# ==============================================================================

def _get_components():
    """Get the global components dict from app.py."""
    from src import app as _app_module
    return _app_module.components


def _get_contact_registry():
    """Get the global contact_registry from app.py."""
    from src import app as _app_module
    return _app_module.contact_registry


def _get_persona_mgr():
    """Get the global persona_mgr from app.py."""
    from src import app as _app_module
    return _app_module.persona_mgr


# ==============================================================================
# HTML/CSS component builders
# ==============================================================================

def _stat_card(value, label: str) -> str:
    """Render a stat card with value and label."""
    return (
        f'<div class="stat-card">'
        f'<div class="stat-label">{label}</div>'
        f'<div class="stat-value">{value}</div>'
        f'</div>'
    )


def _step_html(steps: list) -> str:
    """Render training/operation step list as HTML."""
    parts = []
    for s in steps:
        if isinstance(s, str):
            parts.append('<div class="step-card step-ok">{}</div>'.format(s))
            continue
        cls = "step-ok" if s.ok else "step-fail"
        icon = "✓" if s.ok else "✗"
        detail = "<br><small style='opacity:.6'>{}</small>".format(s.detail) if s.detail else ""
        parts.append('<div class="step-card {cls}">{icon} <b>{name}</b> — {msg}{detail}</div>'.format(
            cls=cls, icon=icon, name=s.name, msg=s.message, detail=detail,
        ))
    return "".join(parts)


def _wordcloud_html(phrases: list, max_items: int = 40) -> str:
    """Render a word cloud from (word, count) pairs."""
    if not phrases:
        return "<p style='text-align:center;opacity:.5'>暂无数据</p>"

    items = phrases[:max_items]
    max_count = items[0][1] if items else 1
    tags = []
    for word, count in items:
        ratio = count / max_count
        size = 0.75 + ratio * 1.5
        opacity = 0.5 + ratio * 0.5
        tags.append(f'<span style="font-size:{size:.2f}em;opacity:{opacity:.2f}">{word}</span>')
    return f'<div class="wordcloud">{"".join(tags)}</div>'


# ==============================================================================
# Persona-related helpers
# ==============================================================================

def _persona_dropdown_choices() -> list[tuple[str, str]]:
    """Return (label, value) pairs for persona dropdown."""
    persona_mgr = _get_persona_mgr()
    if persona_mgr is None:
        return []
    items = persona_mgr.list_personas()
    choices = []
    for p in items:
        count = p["message_count"]
        label = "{} ({}条)".format(p["display_name"], count)
        choices.append((label, p["id"]))
    return choices


def _persona_header_html(persona) -> str:
    """Render persona info bar above the chatbot."""
    if persona is None:
        return '<span style="opacity:.4;font-size:.85em">选择或创建一个人格开始聊天</span>'
    from src.engine.persona import RELATIONSHIP_TYPES
    rel = RELATIONSHIP_TYPES.get(persona.relationship, "")
    name_part = persona.name or ""
    bg_part = " — {}".format(persona.background[:40]) if persona.background else ""
    if persona.relationship == "self":
        return '<span style="font-size:.9em;color:#10b981"><b>本人对话</b> — 学习模式，对话内容会被用于优化模型</span>'
    return '<span style="font-size:.9em"><b>{}</b> {}{}</span>'.format(
        rel, name_part, bg_part,
    )


# ==============================================================================
# Chart builders
# ==============================================================================

def _build_hbar_chart_html(data: list[tuple], title: str = "") -> str:
    """Horizontal bar chart rendered as HTML."""
    if not data:
        return ""
    max_val = max(v for _, v in data) or 1
    bars = []
    for label, count in data:
        pct = count / max_val * 100
        count_str = "{:,}".format(count)
        bars.append(
            '<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
            '<span style="min-width:80px;font-size:.85em;text-align:right;overflow:hidden;'
            'text-overflow:ellipsis;white-space:nowrap">' + str(label) + '</span>'
            '<div style="flex:1;background:var(--block-background-fill);border-radius:4px;overflow:hidden">'
            '<div style="background:var(--color-accent);height:22px;border-radius:4px;'
            'width:{:.1f}%;min-width:2px;transition:width .3s"></div>'.format(pct) +
            '</div>'
            '<span style="min-width:50px;font-size:.8em;opacity:.7">' + count_str + '</span>'
            '</div>'
        )
    header = '<h4 style="margin:0 0 8px">' + title + '</h4>' if title else ''
    return header + '<div style="padding:4px 0">' + "".join(bars) + '</div>'


def _build_vbar_chart_html(data: list[tuple], title: str = "") -> str:
    """Vertical bar chart rendered as HTML (e.g. for 24h distribution)."""
    if not data:
        return ""
    max_val = max(v for _, v in data) or 1
    cols = []
    for label, count in data:
        pct = count / max_val * 100
        cols.append(
            '<div style="display:flex;flex-direction:column;align-items:center;flex:1;min-width:0">'
            '<div style="flex:1;width:100%;display:flex;align-items:flex-end;min-height:150px">'
            '<div style="width:100%;background:var(--color-accent);border-radius:3px 3px 0 0;'
            'min-height:2px;height:{:.1f}%"></div>'.format(pct) +
            '</div>'
            '<span style="font-size:.65em;margin-top:4px;opacity:.7">' + str(label) + '</span>'
            '</div>'
        )
    header = '<h4 style="margin:0 0 8px">' + title + '</h4>' if title else ''
    return (
        header +
        '<div style="display:flex;gap:2px;padding:4px 0;align-items:stretch">'
        + "".join(cols)
        + '</div>'
    )


# ==============================================================================
# Analytics helpers
# ==============================================================================

def _build_relationship_html() -> str:
    """Render relationship distribution from contact registry."""
    contact_registry = _get_contact_registry()
    if contact_registry is None or contact_registry.count() == 0:
        return "<p style='text-align:center;opacity:.5'>联系人数据未导入</p>"
    from src.data.contact_registry import RELATIONSHIP_LABELS
    from collections import Counter
    rel_counts: Counter = Counter()
    for c in contact_registry.contacts.values():
        rel = c.get("relationship", "unknown")
        label = RELATIONSHIP_LABELS.get(rel, rel)
        rel_counts[label] += 1
    data = rel_counts.most_common()
    return _build_hbar_chart_html(data, "联系人关系分布")


def _build_belief_summary_html() -> str:
    """Render belief graph summary."""
    components = _get_components()
    if components is None:
        return ""
    bg = components["belief_graph"]
    all_beliefs = bg.query_all() if hasattr(bg, "query_all") else []
    if not all_beliefs:
        return "<p style='text-align:center;opacity:.5'>暂无信念数据，训练后自动生成</p>"
    high_conf = [b for b in all_beliefs if b.get("confidence", 0) >= 0.8]
    topics = [b.get("topic", "") for b in all_beliefs if b.get("topic")]
    from collections import Counter
    import jieba
    topic_counts = Counter()
    for t in topics:
        for w in jieba.cut(t):
            w = w.strip()
            if len(w) >= 2:
                topic_counts[w] += 1
    top_topic_words = topic_counts.most_common(20)

    html = '<h4 style="margin:0 0 8px">信念图谱概览</h4>'
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">'
    html += _stat_card(len(all_beliefs), "总信念数")
    html += _stat_card(len(high_conf), "高置信度信念")
    html += _stat_card("{:.0%}".format(len(high_conf) / len(all_beliefs)) if all_beliefs else "0%", "高置信度占比")
    html += '</div>'
    if top_topic_words:
        html += '<h4 style="margin:8px 0">信念关键词</h4>'
        html += _wordcloud_html(top_topic_words)
    sample_beliefs = sorted(all_beliefs, key=lambda b: b.get("confidence", 0), reverse=True)[:5]
    if sample_beliefs:
        html += '<h4 style="margin:12px 0 8px">最强信念 Top 5</h4>'
        for b in sample_beliefs:
            conf = b.get("confidence", 0)
            html += '<div style="padding:6px 12px;margin:4px 0;background:var(--block-background-fill);border-radius:6px;border-left:3px solid var(--color-accent)">'
            html += '<b>{}</b>：{}'.format(b.get("topic", ""), b.get("stance", ""))
            html += ' <span style="opacity:.5;font-size:.85em">({:.0%})</span>'.format(conf)
            html += '</div>'
    return html


def _build_persona_html() -> str:
    """Render persona profile HTML."""
    components = _get_components()
    if components is None:
        return ""
    config = components["config"]
    persona_path = Path(config["paths"]["persona_file"])
    if not persona_path.exists():
        return "<p style='text-align:center;padding:20px;opacity:.5'>尚未生成人格画像，请先训练数据</p>"

    with open(persona_path, encoding="utf-8") as f:
        p = yaml.safe_load(f) or {}

    if not p.get("total_messages_analyzed"):
        return "<p style='text-align:center;padding:20px;opacity:.5'>尚未生成人格画像</p>"

    dist = p.get("message_length_distribution", {})
    punc = p.get("punctuation_style", {})
    resp_time = p.get("avg_response_time_seconds")
    resp_str = f"{resp_time:.0f}秒" if resp_time else "N/A"

    avg_len = "{:.1f} 字".format(p.get("avg_message_length", 0))
    emoji_f = "{:.1%}".format(p.get("emoji_frequency", 0))
    vocab_r = "{:.2%}".format(p.get("vocabulary_richness", 0))
    short_p = "{:.0f}%".format(dist.get("short", 0))
    med_p = "{:.0f}%".format(dist.get("medium", 0))
    long_p = "{:.0f}%".format(dist.get("long", 0))

    metrics = (
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">'
        + _stat_card(avg_len, "平均消息长度")
        + _stat_card(emoji_f, "表情使用频率")
        + _stat_card(vocab_r, "词汇丰富度")
        + '</div>'
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px">'
        + _stat_card(resp_str, "平均回复时间")
        + _stat_card(short_p, "短消息占比")
        + _stat_card(med_p, "中等消息占比")
        + _stat_card(long_p, "长消息占比")
        + '</div>'
    )

    exc_f = "{:.2f}/条".format(punc.get("exclamation_freq", 0))
    ell_f = "{:.2f}/条".format(punc.get("ellipsis_freq", 0))
    que_f = "{:.2f}/条".format(punc.get("question_freq", 0))

    punc_html = (
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">'
        + _stat_card(exc_f, "感叹号频率")
        + _stat_card(ell_f, "省略号频率")
        + _stat_card(que_f, "问号频率")
        + '</div>'
    )

    phrases = p.get("top_phrases", [])
    cloud = _wordcloud_html(phrases)

    total_analyzed = "{:,}".format(p.get("total_messages_analyzed", 0))
    return (
        '<h3 style="margin:0 0 12px">人格画像 (' + total_analyzed + ' 条消息分析)</h3>'
        + metrics
        + '<h4 style="margin:8px 0">标点风格</h4>' + punc_html
        + '<h4 style="margin:8px 0">高频短语</h4>' + cloud
    )


def _step_done_html(label, done, detail="") -> str:
    """Render a step done indicator."""
    icon = "✅" if done else "⬜"
    d = f' <span style="opacity:.6">— {detail}</span>' if detail else ""
    return f'<span style="font-size:.95em">{icon} {label}{d}</span>'


def _step3_decrypt_banner_html() -> str:
    """Render the step3 decrypt status banner."""
    from src.app import _detect_pipeline_status
    st = _detect_pipeline_status()
    if st.get("has_decrypted"):
        return '<span style="color:#65a88a">✓ 数据库已解密（{} 个）。</span>'.format(st.get("db_count", 0))
    from src.app import STEP3_GUIDE_HTML
    return STEP3_GUIDE_HTML


# ==============================================================================
# Score/color helpers for eval tab
# ==============================================================================

def _score_color(s: int) -> str:
    """Return color for a score (0-100)."""
    if s >= 75:
        return "#65a88a"
    if s >= 50:
        return "#fbbf24"
    return "#f87171"


def _bar(s: int) -> str:
    """Render a progress bar for a score."""
    color = _score_color(s)
    return (
        f"<div style='background:#3a3035;border-radius:4px;height:8px;margin:4px 0'>"
        f"<div style='background:{color};width:{s}%;height:8px;border-radius:4px;transition:width .4s'></div></div>"
    )
