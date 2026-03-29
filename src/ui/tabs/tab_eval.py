"""Tab: tab_eval — extracted from app.py"""
from __future__ import annotations

from pathlib import Path

import gradio as gr
import json


def render_tab_eval(components=None):

    # ── Relationship Insights Report ─────────────────────
    gr.Markdown("### 关系全景报告\n基于真实聊天记录，生成多维度关系分析报告。包含情感健康评分、依恋风格、沟通密码、信念图谱。")
    report_btn = gr.Button("生成关系全景报告", variant="primary")
    report_html = gr.HTML()

    def _generate_relationship_report():
        if components is None:
            return "<p style='color:red'>系统未初始化，请先完成训练</p>"
        try:
            import datetime as _dt
            cfg = components["config"]

            # ── Load all data ──────────────────────────────
            persona_path = Path(cfg["paths"]["persona_file"])
            persona = {}
            if persona_path.exists():
                import yaml as _rpt_yaml
                with open(persona_path, encoding="utf-8") as f:
                    persona = _rpt_yaml.safe_load(f) or {}

            from src.personality.emotion_analyzer import EmotionAnalyzer as _RptEA
            emo_path = cfg["paths"].get("emotion_file", "data/emotion_profile.yaml")
            emo = _RptEA.load(emo_path) or {}

            digest_path = Path("data/mediation_digest.json")
            digest = ""
            if digest_path.exists():
                try:
                    d = json.loads(digest_path.read_text(encoding="utf-8"))
                    digest = d.get("digest", "")
                except Exception:
                    pass

            beliefs_path = Path(cfg["paths"].get("beliefs_file", "data/beliefs.json"))
            beliefs_raw = {}
            if beliefs_path.exists():
                try:
                    rb = json.loads(beliefs_path.read_text(encoding="utf-8"))
                    beliefs_raw = rb.get("beliefs", rb) if isinstance(rb, dict) else {}
                except Exception:
                    pass

            thinking_path = Path(cfg["paths"].get("thinking_model_file", "data/thinking_model.txt"))
            thinking_text = ""
            if thinking_path.exists():
                try:
                    thinking_text = thinking_path.read_text(encoding="utf-8")[:4000]
                except Exception:
                    pass

            # ── Extract fields ─────────────────────────────
            basic = persona.get("basic_info", {})
            name = basic.get("name", basic.get("姓名", "TA"))
            gender = basic.get("gender", basic.get("性别", ""))
            age = basic.get("age", basic.get("年龄", ""))
            location = basic.get("location", basic.get("所在地", ""))
            total_msgs = persona.get("total_messages_analyzed", 0)
            avg_len = persona.get("avg_message_length", 0)
            avg_resp = persona.get("avg_response_time_seconds", 0)
            emoji_freq = persona.get("emoji_frequency", 0)
            vocab_rich = persona.get("vocabulary_richness", 0)
            msg_dist = persona.get("message_length_distribution", {})
            catchphrases = persona.get("vocab_bank", {}).get("catchphrases", [])[:10]
            slang = persona.get("vocab_bank", {}).get("slang", [])[:8]
            top_phrases = [(p[0], p[1]) for p in (persona.get("top_phrases") or [])[:12] if isinstance(p, (list, tuple)) and len(p) == 2]

            emo_dist = emo.get("emotion_distribution", {})
            emo_triggers = emo.get("emotion_triggers", emo.get("triggers", {}))
            emo_transitions = emo.get("emotion_transitions", {})

            # ── Metric computations ────────────────────────
            # Remove neutral for ratio calculations
            active_emo = {k: v for k, v in emo_dist.items() if k != "neutral"}
            total_active = max(sum(active_emo.values()), 1)

            POS_KEYS = {"joy", "coquettish", "gratitude", "pride", "touched", "excitement"}
            NEG_KEYS = {"anger", "anxiety", "disappointment", "sadness", "wronged", "heartache", "jealousy"}
            pos_sum = sum(v for k, v in active_emo.items() if k in POS_KEYS)
            neg_sum = sum(v for k, v in active_emo.items() if k in NEG_KEYS)
            pos_ratio = pos_sum / total_active
            neg_ratio = neg_sum / total_active
            # Gottman magic ratio benchmark is 5:1
            magic_ratio = pos_sum / max(neg_sum, 1)

            # Emotion repair speed: transitions back to neutral / total transitions
            to_neutral = sum(v for k, v in emo_transitions.items() if k.endswith("->neutral"))
            total_transitions = max(sum(emo_transitions.values()), 1)
            repair_rate = to_neutral / total_transitions

            # 5 Gottman-inspired dimensions (0–100)
            # 1. Emotional connection: positive emo density
            d_connection = min(100, round(pos_ratio * 140))
            # 2. Conflict health: penalize high anger/contempt ratio
            anger_v = active_emo.get("anger", 0)
            wronged_v = active_emo.get("wronged", 0)
            d_conflict = max(0, round(100 - (anger_v + wronged_v) / total_active * 300))
            # 3. Trust & security: penalize anxiety + jealousy
            anx_v = active_emo.get("anxiety", 0)
            jeal_v = active_emo.get("jealousy", 0)
            d_trust = max(0, round(100 - (anx_v + jeal_v) / total_active * 200))
            # 4. Communication vitality: avg_len, emoji_freq, response_time
            resp_score = max(0, 100 - min(avg_resp, 600) / 6)
            len_score = min(100, avg_len / 15 * 100)
            d_comm = round((resp_score * 0.5 + len_score * 0.3 + emoji_freq * 2000 * 0.2))
            d_comm = min(100, max(0, d_comm))
            # 5. Emotional resilience: repair rate
            d_resilience = min(100, round(repair_rate * 160))

            def score_color(s):
                if s >= 75: return "#65a88a"
                if s >= 50: return "#fbbf24"
                return "#f87171"

            def score_label(s):
                if s >= 80: return "优秀"
                if s >= 65: return "良好"
                if s >= 45: return "一般"
                return "需关注"

            # ── Infer attachment style ─────────────────────
            anx_pct = anx_v / total_active
            longing_v = active_emo.get("longing", 0)
            # Anxious markers: high anxiety, longing, low trust score, "分离焦虑" in thinking
            anxious_score = anx_pct * 3 + (longing_v / total_active) + (1 if "分离焦虑" in thinking_text else 0) + (1 if "先试探安全性" in thinking_text else 0)
            # Avoidant markers: low coquettish, "切断式" patterns
            coquettish_pct = active_emo.get("coquettish", 0) / total_active
            avoidant_score = (0.3 - coquettish_pct) + (1 if "切断式" in thinking_text else 0) + (1 if "收回互动权限" in thinking_text else 0)
            # Secure markers: high repair rate, positive ratio
            secure_score = repair_rate * 2 + pos_ratio

            if anxious_score > avoidant_score and anxious_score > secure_score:
                attach_type = "焦虑型依恋"
                attach_icon = "🔍"
                attach_color = "#fb923c"
                attach_desc = "在关系中倾向于主动确认，回应慢时容易激活『我是否被在乎』的警报系统。需要持续的安全信号，一旦被接住就能迅速软化并恢复合作。"
            elif avoidant_score > anxious_score and avoidant_score > secure_score:
                attach_type = "回避型依恋"
                attach_icon = "🛡️"
                attach_color = "#60a5fa"
                attach_desc = "在亲密关系中保持情感距离以维护安全感。遇到压力时更可能用切断式回应来保护自己，但内心有真实的依恋需求。"
            else:
                attach_type = "安全型依恋（倾向）"
                attach_icon = "⚡"
                attach_color = "#65a88a"
                attach_desc = "基本能在情绪激活后较快恢复，修复意愿强，在冲突后能重新回到合作状态。关系稳定性相对较高。"

            # ── Beliefs: pick high-confidence, varied topics ──
            belief_list = []
            if isinstance(beliefs_raw, dict):
                for b in beliefs_raw.values():
                    if isinstance(b, dict) and b.get("confidence", 0) >= 0.85:
                        belief_list.append(b)
            belief_list.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            seen_topics = set()
            deduped_beliefs = []
            for b in belief_list:
                topic = b.get("topic", "")
                if topic not in seen_topics:
                    seen_topics.add(topic)
                    deduped_beliefs.append(b)
                if len(deduped_beliefs) >= 6:
                    break

            # ── Emotion map: top non-neutral emotions ─────
            emo_map_colors = {
                "joy": "#fbbf24", "coquettish": "#f472b6", "gratitude": "#34d399",
                "pride": "#a78bfa", "touched": "#f9a8d4", "excitement": "#fb923c",
                "longing": "#818cf8", "curiosity": "#60a5fa",
                "anger": "#ef4444", "anxiety": "#fb923c", "disappointment": "#a8969a",
                "sadness": "#818cf8", "wronged": "#c084fc", "heartache": "#f87171",
                "jealousy": "#e879f9",
            }
            emo_label_map = {
                "joy": "开心", "coquettish": "撒娇", "gratitude": "感激",
                "pride": "自豪", "touched": "感动", "excitement": "兴奋",
                "longing": "思念", "curiosity": "好奇",
                "anger": "愤怒", "anxiety": "焦虑", "disappointment": "失望",
                "sadness": "悲伤", "wronged": "委屈", "heartache": "心痛",
                "jealousy": "嫉妒",
            }
            sorted_active = sorted(active_emo.items(), key=lambda x: x[1], reverse=True)[:10]
            max_emo_val = max((v for _, v in sorted_active), default=1)

            today = _dt.date.today().strftime("%Y年%m月%d日")

            # ════════════════════════════════════════════════
            # HTML BUILD — desktop-first grid layout
            # ════════════════════════════════════════════════

            def section(title, icon, color, body):
                return f"""<div style="background:#2a2225;border-radius:14px;padding:20px 22px;height:100%;box-sizing:border-box">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #ffffff0d">
    <span style="font-size:16px">{icon}</span>
    <span style="font-size:13px;font-weight:700;color:{color};letter-spacing:.05em;text-transform:uppercase">{title}</span>
    </div>
    {body}
    </div>"""

            def metric_row(label, val, color, note=""):
                note_html = f"<span style='color:#5a4d50;font-size:11px;margin-left:6px'>{note}</span>" if note else ""
                return (
                    f"<div style='display:flex;align-items:center;margin-bottom:12px'>"
                    f"<span style='width:110px;font-size:12px;color:#a8969a;flex-shrink:0'>{label}</span>"
                    f"<div style='flex:1;height:8px;background:#1e181b;border-radius:4px;overflow:hidden'>"
                    f"<div style='width:{val}%;height:100%;background:{color};border-radius:4px'></div>"
                    f"</div>"
                    f"<span style='width:36px;text-align:right;font-size:12px;color:{color};margin-left:8px'>{val}</span>"
                    f"{note_html}"
                    f"</div>"
                )

            def stat_box(label, value, sub=""):
                sub_html = ("<div style='font-size:10px;color:#5a4d50;margin-top:2px'>"
                            + sub + "</div>") if sub else ""
                return (
                    f"<div style='background:#1e181b;border-radius:10px;padding:14px 16px;text-align:center'>"
                    f"<div style='font-size:22px;font-weight:700;color:#f0e8e4'>{value}</div>"
                    f"<div style='font-size:11px;color:#7a6b6f;margin-top:3px'>{label}</div>"
                    f"{sub_html}"
                    f"</div>"
                )

            def tag(text, color="#a8969a"):
                return (
                    f"<span style='display:inline-block;padding:4px 10px;border-radius:6px;"
                    f"background:{color}18;color:{color};border:1px solid {color}30;"
                    f"font-size:12px;margin:3px'>{text}</span>"
                )

            # Section 1: 基础数据速写
            stat_row = (
                f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px'>"
                f"{stat_box('消息总量', f'{total_msgs:,}' if total_msgs else '—', '已分析')}"
                f"{stat_box('平均字数', f'{avg_len:.1f}', '字/条')}"
                f"{stat_box('平均回复', f'{int(avg_resp//60)}m{int(avg_resp%60)}s' if avg_resp else '—', '响应时间')}"
                f"{stat_box('词汇丰富度', f'{vocab_rich:.1%}' if vocab_rich else '—', '类型/词元比')}"
                f"</div>"
            )
            msg_dist_html = ""
            if msg_dist:
                for lbl, pct in [("短消息(≤10字)", msg_dist.get("short", 0)), ("中消息", msg_dist.get("medium", 0)), ("长消息(>50字)", msg_dist.get("long", 0))]:
                    c = "#60a5fa" if "短" in lbl else "#a78bfa" if "中" in lbl else "#f472b6"
                    msg_dist_html += metric_row(lbl, min(100, int(pct)), c)
            sec1_body = stat_row + msg_dist_html
            if catchphrases:
                sec1_body += f"<div style='margin-top:12px'><span style='font-size:11px;color:#5a4d50;display:block;margin-bottom:6px'>口头禅</span>"
                sec1_body += "".join(tag(p, "#818cf8") for p in catchphrases[:8])
                sec1_body += "</div>"
            sec1 = section("沟通速写", "📊", "#60a5fa", sec1_body)

            # Section 2: 情感色谱
            emo_bars_html = ""
            for emo_key, emo_val in sorted_active:
                pct = round(emo_val / max_emo_val * 100)
                c = emo_map_colors.get(emo_key, "#a8969a")
                lbl = emo_label_map.get(emo_key, emo_key)
                raw_pct = round(emo_val / total_active * 100)
                emo_bars_html += (
                    f"<div style='display:flex;align-items:center;margin-bottom:8px'>"
                    f"<span style='width:44px;font-size:12px;color:#a8969a;flex-shrink:0;text-align:right;margin-right:10px'>{lbl}</span>"
                    f"<div style='flex:1;height:16px;background:#1e181b;border-radius:8px;overflow:hidden'>"
                    f"<div style='width:{pct}%;height:100%;background:linear-gradient(90deg,{c}66,{c});border-radius:8px'></div>"
                    f"</div>"
                    f"<span style='width:32px;font-size:11px;color:#7a6b6f;margin-left:8px;text-align:right'>{raw_pct}%</span>"
                    f"</div>"
                )
            # positive/negative summary
            ratio_label = f"正负情绪比 {pos_sum}:{neg_sum} ≈ {magic_ratio:.1f}:1"
            ratio_color = "#65a88a" if magic_ratio >= 5 else "#fbbf24" if magic_ratio >= 2 else "#f87171"
            emo_bars_html += (
                f"<div style='margin-top:14px;padding:10px 14px;background:#1e181b;"
                f"border-radius:8px;font-size:12px;color:{ratio_color}'>"
                f"Gottman 黄金比例基准 5:1 ·&nbsp;<b>{ratio_label}</b>"
                f"</div>"
            )
            sec2 = section("情感色谱", "🌈", "#fbbf24", emo_bars_html)

            # Section 3: 5 dimensions
            dims = [
                ("情感联结", d_connection, "与伴侣的亲密感、积极情绪密度"),
                ("冲突健康", d_conflict, "愤怒/委屈占比，越高越健康"),
                ("信任安全感", d_trust, "焦虑/嫉妒占比，越高越稳定"),
                ("沟通活跃度", d_comm, "响应速度、消息长度综合"),
                ("情绪恢复力", d_resilience, "从负面情绪回到平静的速度"),
            ]
            dims_html = ""
            for dim_name, dim_val, dim_desc in dims:
                c = score_color(dim_val)
                lbl = score_label(dim_val)
                dims_html += (
                    f"<div style='margin-bottom:14px'>"
                    f"<div style='display:flex;justify-content:space-between;margin-bottom:5px'>"
                    f"<span style='font-size:13px;color:#e6dcd8'>{dim_name}</span>"
                    f"<span style='font-size:12px;color:{c};font-weight:600'>{dim_val} · {lbl}</span>"
                    f"</div>"
                    f"<div style='height:8px;background:#1e181b;border-radius:4px;overflow:hidden;margin-bottom:4px'>"
                    f"<div style='width:{dim_val}%;height:100%;background:linear-gradient(90deg,{c}66,{c});border-radius:4px'></div>"
                    f"</div>"
                    f"<div style='font-size:11px;color:#5a4d50'>{dim_desc}</div>"
                    f"</div>"
                )
            sec3 = section("关系健康五维度", "💎", "#a78bfa", dims_html)

            # Section 4: 依恋风格
            attach_html = (
                f"<div style='text-align:center;padding:16px 0 20px'>"
                f"<div style='font-size:32px;margin-bottom:8px'>{attach_icon}</div>"
                f"<div style='font-size:18px;font-weight:700;color:{attach_color}'>{attach_type}</div>"
                f"</div>"
                f"<div style='font-size:13px;color:#a8969a;line-height:1.8;padding:14px;background:#1e181b;border-radius:10px'>"
                f"{attach_desc}</div>"
            )
            if thinking_text:
                # Extract first 2 reaction patterns from thinking model
                lines = [l.strip() for l in thinking_text.split("\n") if l.strip() and "→" in l][:3]
                if lines:
                    attach_html += "<div style='margin-top:14px'><span style='font-size:11px;color:#5a4d50;display:block;margin-bottom:8px'>典型反应模式（来自思维建模）</span>"
                    for line in lines:
                        parts = line.split("→")
                        if len(parts) == 2:
                            trigger_txt = parts[0].lstrip("0123456789). ").strip()
                            react_txt = parts[1].strip()
                            attach_html += (
                                f"<div style='padding:8px 12px;background:#1e2a25;border-radius:8px;"
                                f"margin-bottom:6px;font-size:12px'>"
                                f"<span style='color:#7a6b6f'>触发：</span><span style='color:#a8969a'>{trigger_txt[:40]}</span>"
                                f"<br><span style='color:#7a6b6f'>反应：</span><span style='color:#65a88a'>{react_txt[:60]}</span>"
                                f"</div>"
                            )
                    attach_html += "</div>"
            sec4 = section("依恋风格分析", "🔗", attach_color, attach_html)

            # Section 5: 关系动力摘要 (full width)
            digest_section = ""
            if digest:
                digest_lines_html = ""
                for line in digest.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("- **") or line.startswith("**"):
                        # Bold heading line
                        import re as _re
                        line_html = _re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#f0e8e4'>\1</b>", line.lstrip("- "))
                        digest_lines_html += f"<div style='margin-bottom:8px;padding:10px 14px;background:#1e181b;border-radius:8px;font-size:13px;color:#a8969a;line-height:1.7'>{line_html}</div>"
                    else:
                        digest_lines_html += f"<div style='font-size:13px;color:#a8969a;line-height:1.7;margin-bottom:6px'>{line}</div>"
                digest_section = section("关系动力摘要", "🔬", "#f472b6",
                    f"<div style='columns:2;gap:16px'>{digest_lines_html}</div>")

            # Section 6: 核心信念
            beliefs_html = ""
            for b in deduped_beliefs:
                conf = b.get("confidence", 0)
                topic = b.get("topic", "")
                stance = b.get("stance", "")
                conf_c = "#65a88a" if conf >= 0.9 else "#fbbf24" if conf >= 0.75 else "#a8969a"
                beliefs_html += (
                    f"<div style='padding:12px 14px;background:#1e181b;border-radius:10px;"
                    f"margin-bottom:8px;border-left:3px solid {conf_c}44'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
                    f"<span style='font-size:11px;color:#7a6b6f;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>{topic}</span>"
                    f"<span style='font-size:11px;color:{conf_c}'>置信度 {conf:.0%}</span>"
                    f"</div>"
                    f"<div style='font-size:13px;color:#e6dcd8;line-height:1.6'>{stance}</div>"
                    f"</div>"
                )
            sec6 = section("核心信念图谱", "🧠", "#c084fc", beliefs_html or "<p style='color:#5a4d50'>暂无信念数据</p>")

            # Section 7: 情绪触发地图
            trigger_html = ""
            trigger_groups = [
                ("anger", "愤怒", "#ef4444"),
                ("anxiety", "焦虑", "#fb923c"),
                ("wronged", "委屈", "#a78bfa"),
                ("sadness", "悲伤", "#818cf8"),
                ("disappointment", "失望", "#7a6b6f"),
            ]
            for tkey, tlabel, tcolor in trigger_groups:
                words = []
                tr_info = emo_triggers.get(tkey, [])
                if isinstance(tr_info, list):
                    words = [w for w in tr_info if isinstance(w, str)][:6]
                elif isinstance(tr_info, dict):
                    words = tr_info.get("top_words", [])[:6]
                if not words:
                    continue
                trigger_html += (
                    f"<div style='margin-bottom:12px'>"
                    f"<span style='font-size:12px;font-weight:600;color:{tcolor};display:block;margin-bottom:6px'>{tlabel}</span>"
                    f"{''.join(tag(w, tcolor) for w in words)}"
                    f"</div>"
                )
            sec7 = section("情绪触发地图", "⚡", "#f87171", trigger_html or "<p style='color:#5a4d50'>暂无触发数据</p>")

            # ── Assemble final HTML ─────────────────────────
            html = f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;
    color:#f0e8e4;background:#1e181b;padding:28px;border-radius:16px;min-width:700px">

    <!-- Header -->
    <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:24px;
    padding-bottom:18px;border-bottom:1px solid #2a2225">
    <div>
    <div style="font-size:22px;font-weight:800;background:linear-gradient(135deg,#c084fc,#f472b6,#fb923c);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px">
    {name} 的关系全景报告</div>
    <div style="font-size:13px;color:#5a4d50">
    {gender}{('·' + age + '岁') if age else ''}{('·' + location) if location else ''}
    &nbsp;·&nbsp;基于 {total_msgs:,} 条真实消息 &nbsp;·&nbsp; {today}
    </div>
    </div>
    <div style="font-size:11px;color:#5a4d50;text-align:right">心译 · AI 关系洞察<br>Gottman / EFT 框架</div>
    </div>

    <!-- Row 1: stats + emotion spectrum -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
    {sec1}
    {sec2}
    </div>

    <!-- Row 2: 5 dimensions + attachment -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
    {sec3}
    {sec4}
    </div>

    <!-- Row 3: relationship dynamics (full width) -->
    {"<div style='margin-bottom:14px'>" + digest_section + "</div>" if digest_section else ""}

    <!-- Row 4: beliefs + triggers -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
    {sec6}
    {sec7}
    </div>

    </div>"""
            return html

        except Exception as e:
            logger.exception("Report generation failed")
            return f"<p style='color:red'>报告生成失败: {e}</p>"

    report_btn.click(fn=_generate_relationship_report, outputs=report_html)

    gr.Markdown("---")

    gr.Markdown(
        "### 分身诊断\n"
        "通过向分身提问，评估它对你思维模式的还原程度，并给出是否需要继续校准的建议。"
    )
    diag_btn = gr.Button("开始诊断", variant="primary")
    diag_result_html = gr.HTML()

    def run_twin_diagnosis():
        if components is None:
            return "<p style='color:red'>系统未初始化</p>"
        try:
            import openai as _oai
            from src.data.partner_config import load_twin_mode as _ltm_diag

            c = components
            _tw_mode = _ltm_diag()
            engine = c["chat_engine"]

            # ── 1. 思维模式探针问题 ──────────────────────────────
            thinking_probes = [
                ("决策偏好", "你需要在两件同样重要的事里选一件，你会怎么决定？"),
                ("冲突处理", "如果身边的人做了让你不舒服的事，你第一反应会怎么做？"),
                ("不确定感", "面对一件完全没把握的事，你会先动手还是先想清楚再说？"),
                ("情绪表达", "你难过的时候，更倾向于自己消化还是说出来？"),
                ("价值排序", "工作和休息之间，你怎么给自己划边界？"),
            ]
            tone_probes = [
                ("语气温度", "今天过得怎么样？"),
                ("回应长度", "随便聊一件最近让你开心的小事。"),
            ]

            thinking_replies: list[tuple[str, str, str]] = []
            tone_replies: list[tuple[str, str, str]] = []

            def _ask(question: str) -> str:
                try:
                    resp = engine.chat(question)
                    return (resp or "").strip()
                except Exception:
                    return ""

            for dim, q in thinking_probes:
                thinking_replies.append((dim, q, _ask(q)))
            for dim, q in tone_probes:
                tone_replies.append((dim, q, _ask(q)))

            # ── 2. 构造 LLM 评估 prompt ──────────────────────────
            qa_block = "\n".join(
                f"[{dim}] 问：{q}\n分身答：{a if a else '（无回复）'}"
                for dim, q, a in thinking_replies + tone_replies
            )

            profile_hint = ""
            pb = c.get("prompt_builder")
            if pb and hasattr(pb, "profile") and pb.profile:
                p = pb.profile
                profile_hint = (
                    f"已知真人画像摘要：性格={p.get('personality','未知')}，"
                    f"价值观={p.get('values','未知')}，"
                    f"沟通风格={p.get('communication_style','未知')}\n\n"
                )

            eval_prompt = f"""{profile_hint}以下是对数字分身进行诊断的问答记录。
    请从两个维度评估：
    1. 思维模式还原度（主要）：决策逻辑、冲突处理方式、不确定性应对、情绪模式、价值排序是否符合真人特征。满分100分，权重70%。
    2. 语气一致性（次要）：回复温度、表达方式是否接近真人风格。满分100分，权重30%。

    问答记录：
    {qa_block}

    请用以下 JSON 格式输出，不要输出任何多余内容：
    {{
    "thinking_score": <0-100整数>,
    "tone_score": <0-100整数>,
    "thinking_issues": ["<问题1>", "<问题2>"],
    "tone_issues": ["<问题1>"],
    "suggestions": ["<具体优化建议1>", "<具体优化建议2>", "<具体优化建议3>"],
    "calibration_needed": <true|false>,
    "calibration_reason": "<一句话说明是否需要继续校准>"
    }}"""

            cfg = c.get("config", {}) or {}
            api_cfg = cfg.get("api", {}) or {}
            api_base = api_cfg.get("base_url") or "https://api.openai.com/v1"
            api_key = api_cfg.get("api_key", "")
            model = api_cfg.get("model", "gpt-4o")
            extra_headers = api_cfg.get("headers", {})

            _cli = _oai.OpenAI(api_key=api_key, base_url=api_base, default_headers=extra_headers)
            raw_eval = (_cli.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": eval_prompt}],
                temperature=0.2,
            ).choices[0].message.content or "").strip()

            import json as _json
            import re as _re_diag
            _m = _re_diag.search(r'\{[\s\S]+\}', raw_eval)
            ev = _json.loads(_m.group()) if _m else {}

            thinking_score = int(ev.get("thinking_score", 0))
            tone_score = int(ev.get("tone_score", 0))
            overall = round(thinking_score * 0.7 + tone_score * 0.3)
            calibration_needed = ev.get("calibration_needed", False)
            calibration_reason = ev.get("calibration_reason", "")
            suggestions = ev.get("suggestions", [])
            thinking_issues = ev.get("thinking_issues", [])
            tone_issues = ev.get("tone_issues", [])

            def _score_color(s):
                if s >= 75: return "#65a88a"
                if s >= 50: return "#f59e0b"
                return "#ef4444"

            def _bar(s):
                color = _score_color(s)
                return (
                    f"<div style='background:#3a3035;border-radius:4px;height:8px;margin:4px 0'>"
                    f"<div style='background:{color};width:{s}%;height:8px;border-radius:4px;transition:width .4s'></div></div>"
                )

            issues_html = ""
            if thinking_issues:
                issues_html += "<div style='margin-top:6px;font-size:.85em;color:#c0a8b0'>"
                for iss in thinking_issues:
                    issues_html += f"<span style='margin-right:8px'>· {iss}</span>"
                issues_html += "</div>"

            tone_issues_html = ""
            if tone_issues:
                tone_issues_html += "<div style='margin-top:4px;font-size:.85em;color:#c0a8b0'>"
                for iss in tone_issues:
                    tone_issues_html += f"<span style='margin-right:8px'>· {iss}</span>"
                tone_issues_html += "</div>"

            sug_html = "".join(
                f"<li style='margin:6px 0;color:#d4c4c8'>{s}</li>"
                for s in suggestions
            )

            calib_color = "#ef4444" if calibration_needed else "#65a88a"
            calib_icon = "⚠️ 建议继续校准" if calibration_needed else "✓ 暂时不需要校准"

            html = f"""<div style='font-family:var(--font);padding:20px;background:#1e181b;border-radius:12px;color:#e0d4d8'>

    <div style='display:flex;align-items:center;gap:16px;margin-bottom:20px'>
    <div style='text-align:center;background:#2a2225;padding:14px 20px;border-radius:10px;min-width:80px'>
    <div style='font-size:2em;font-weight:700;color:{_score_color(overall)}'>{overall}</div>
    <div style='font-size:.75em;color:#a8969a;margin-top:2px'>综合评分</div>
    </div>
    <div style='flex:1'>
    <div style='font-size:.85em;color:#a8969a;margin-bottom:4px'>思维模式还原度 <span style='color:{_score_color(thinking_score)};font-weight:600'>{thinking_score}/100</span></div>
    {_bar(thinking_score)}
    {issues_html}
    <div style='font-size:.85em;color:#a8969a;margin-top:10px;margin-bottom:4px'>语气一致性 <span style='color:{_score_color(tone_score)};font-weight:600'>{tone_score}/100</span></div>
    {_bar(tone_score)}
    {tone_issues_html}
    </div>
    </div>

    <div style='background:#2a2225;border-radius:8px;padding:14px;margin-bottom:14px'>
    <div style='font-size:.85em;color:#a8969a;margin-bottom:8px;font-weight:600'>优化建议</div>
    <ul style='margin:0;padding-left:18px;line-height:1.8'>{sug_html}</ul>
    </div>

    <div style='border:1px solid {calib_color}33;border-radius:8px;padding:12px 16px;display:flex;align-items:flex-start;gap:10px'>
    <span style='color:{calib_color};font-size:1em;white-space:nowrap'>{calib_icon}</span>
    <span style='font-size:.9em;color:#d4c4c8;line-height:1.6'>{calibration_reason}</span>
    </div>

    </div>"""
            return html

        except Exception as e:
            logger.exception("Twin diagnosis failed")
            return f"<p style='color:red'>诊断失败: {e}</p>"

    diag_btn.click(fn=run_twin_diagnosis, outputs=diag_result_html)


    # ================================================================
    # Tab: Personality Calibration (人格校准)
    # ================================================================
