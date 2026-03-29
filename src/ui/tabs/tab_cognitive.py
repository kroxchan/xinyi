"""Tab: tab_cognitive — extracted from app.py"""
from __future__ import annotations

from pathlib import Path

import gradio as gr


def render_tab_cognitive(components=None, demo=None):
    gr.Markdown(
        "### 人格校准\n"
        "通过情境任务校准分身的认知模型。\n"
        "这些不是问卷，而是有约束的情境——**没有标准答案，你怎么想就怎么说**。\n"
        "系统会从你的选择中反推你的思维逻辑，而不是相信自述。\n\n"
        "做得越多，心译越懂你。学习完成即可使用对话功能。"
    )

    with gr.Accordion("基本信息（让数字分身知道自己是谁）", open=True):
        with gr.Row():
            bi_name = gr.Textbox(label="姓名", placeholder="真实姓名")
            bi_nickname = gr.Textbox(label="昵称", placeholder="朋友怎么叫你")
        with gr.Row():
            bi_gender = gr.Dropdown(label="性别", choices=["男", "女", "其他"], value=None, allow_custom_value=True)
            bi_age = gr.Textbox(label="年龄/年龄段", placeholder="如 23 或 20出头")
        with gr.Row():
            bi_location = gr.Textbox(label="所在城市", placeholder="如 深圳")
            bi_occupation = gr.Textbox(label="职业/身份", placeholder="如 大学生、程序员")
        bi_extra = gr.Textbox(label="其他补充", placeholder="任何你想让数字分身记住的身份信息", lines=2)
        bi_save_btn = gr.Button("保存基本信息", variant="primary")
        bi_status = gr.HTML(value="")

        def _load_basic_info():
            if not components or not components.get("config"):
                return "", "", None, "", "", "", ""
            p = Path(components["config"]["paths"]["persona_file"])
            if not p.exists():
                return "", "", None, "", "", "", ""
            import yaml as _yaml
            with open(p, encoding="utf-8") as f:
                prof = _yaml.safe_load(f) or {}
            bi = prof.get("basic_info", {})
            return (
                bi.get("name", ""), bi.get("nickname", ""),
                bi.get("gender"), bi.get("age", ""),
                bi.get("location", ""), bi.get("occupation", ""),
                bi.get("extra", ""),
            )

        def _save_basic_info(name, nickname, gender, age, location, occupation, extra):
            if not components or not components.get("config"):
                return "<span style='color:#ef4444'>系统未初始化</span>"
            import yaml as _yaml
            p = Path(components["config"]["paths"]["persona_file"])
            prof = {}
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    prof = _yaml.safe_load(f) or {}
            bi = {}
            if name.strip(): bi["name"] = name.strip()
            if nickname.strip(): bi["nickname"] = nickname.strip()
            if gender: bi["gender"] = gender
            if age.strip(): bi["age"] = age.strip()
            if location.strip(): bi["location"] = location.strip()
            if occupation.strip(): bi["occupation"] = occupation.strip()
            if extra.strip(): bi["extra"] = extra.strip()
            prof["basic_info"] = bi
            with open(p, "w", encoding="utf-8") as f:
                _yaml.dump(prof, f, allow_unicode=True, default_flow_style=False)

            if components.get("prompt_builder"):
                components["prompt_builder"].profile = prof
                components["prompt_builder"].regenerate_guidance()

            filled = [v for v in bi.values() if v]
            return f"<span style='color:#10b981'>✓ 已保存 {len(filled)} 项基本信息，identity.md 已更新</span>"

        bi_save_btn.click(
            fn=_save_basic_info,
            inputs=[bi_name, bi_nickname, bi_gender, bi_age, bi_location, bi_occupation, bi_extra],
            outputs=[bi_status],
        )
        if demo is not None:
            demo.load(
                fn=_load_basic_info,
                outputs=[bi_name, bi_nickname, bi_gender, bi_age, bi_location, bi_occupation, bi_extra],
            )
    task_progress_html = gr.HTML(value="")
    with gr.Group():
        task_display = gr.Markdown(value="*点击「开始校准」获取第一道题*")
        task_response = gr.Textbox(
            label="你的回答",
            placeholder="认真想，不需要标准答案。你平时怎么做就怎么说。",
            lines=5,
        )
        with gr.Row():
            next_task_btn = gr.Button("开始校准", variant="primary", scale=2)
            submit_task_btn = gr.Button("提交并下一题", variant="secondary", scale=2)
    task_current_id = gr.State(value="")
    task_current_prompt = gr.State(value="")
    task_analysis_output = gr.Markdown(value="")

    with gr.Accordion("矛盾检测（校准完成后可用）", open=False):
        scan_contradictions_btn = gr.Button("扫描信念矛盾", variant="secondary")
        contradiction_output = gr.Markdown(value="")

    def _task_progress_html():
        if components is None:
            return ""
        tl = components.get("task_library")
        if not tl:
            return ""
        done = tl.get_completed_count()
        total = tl.get_total_count()
        pct = int(done / max(total, 1) * 100) if total else 0
        pct = min(pct, 100)
        bar_color = "#10b981" if done > 0 else "#f59e0b"
        status_text = f"已完成 {done} 题" if done > 0 else "尚未开始"
        return (
            f"<div style='padding:12px 16px;background:#2a2225;border-radius:10px;'>"
            f"<div style='display:flex;justify-content:space-between;margin-bottom:6px;'>"
            f"<span>已完成 <b>{done}</b>/{total} 题</span>"
            f"<span style='color:{bar_color};font-weight:600'>{status_text}</span></div>"
            f"<div style='background:#5a4d50;border-radius:4px;height:8px;'>"
            f"<div style='background:{bar_color};height:8px;border-radius:4px;"
            f"width:{pct}%;transition:width .3s'></div>"
            f"</div></div>"
        )

    def _next_task():
        if components is None:
            return "系统未初始化", "", "", _task_progress_html()
        tl = components.get("task_library")
        if not tl:
            return "任务库未加载", "", "", ""
        tl.ensure_seed_tasks()
        task = tl.get_next_task()
        if not task:
            return (
                "**题库初始化失败。** 默认校准题没有成功加载，请重启后重试。",
                "",
                "",
                _task_progress_html(),
            )
        done = tl.get_completed_count()
        num = done + 1
        dim_name = TASK_DIMENSIONS.get(task["dimension"], task["dimension"])
        md = f"### 第 {num} 题 · {dim_name}\n\n{task['prompt']}"
        return md, task["id"], task["prompt"], _task_progress_html()

    def _submit_task(task_id, task_prompt, response_text):
        if not task_id or not response_text.strip():
            return "请先获取任务并填写回答", _task_progress_html(), gr.update(), "", "", gr.update()
        if components is None:
            return "系统未初始化", "", gr.update(), "", "", gr.update()
        tl = components["task_library"]
        ie = components["inference_engine"]
        bg = components["belief_graph"]
        cd = components["contradiction_detector"]

        task_result = tl.record_response(task_id, response_text, task_prompt)
        analysis = ie.analyze_response(task_result)

        new_beliefs_added = 0
        if analysis:
            for b in analysis.get("inferred_beliefs", []):
                if not b.get("topic"):
                    continue
                b["source"] = f"task_{task_id}"
                bid = bg.add_belief(b)
                new_beliefs_added += 1
                contras = cd.check_new_belief(b, bg.query_all()[:30])
                for contra in contras:
                    bg.add_contradiction(
                        bid,
                        contra.get("belief_a", ""),
                        contra.get("explanation", ""),
                    )
            bg.save()

        md_parts = []
        if analysis.get("decision_logic"):
            md_parts.append(f"**决策逻辑**: {analysis['decision_logic']}")
        if analysis.get("priorities"):
            md_parts.append(f"**优先级**: {' > '.join(analysis['priorities'])}")
        if analysis.get("thinking_style"):
            md_parts.append(f"**思维特征**: {analysis['thinking_style']}")
        if new_beliefs_added:
            md_parts.append(f"*已提取 {new_beliefs_added} 条新信念写入图谱*")

        done = tl.get_completed_count()

        analysis_md = "\n\n".join(md_parts) if md_parts else "分析完成"

        next_task = tl.get_next_task()
        if next_task:
            num = done + 1
            dim_name = TASK_DIMENSIONS.get(next_task["dimension"], next_task["dimension"])
            next_md = f"### 第 {num} 题 · {dim_name}\n\n{next_task['prompt']}"
            return analysis_md, _task_progress_html(), next_md, next_task["id"], next_task["prompt"], gr.update(value="")
        return analysis_md, _task_progress_html(), "**所有任务已完成！**", "", "", gr.update(value="")

    def _scan_contradictions():
        if components is None:
            return "系统未初始化"
        cd = components["contradiction_detector"]
        bg = components["belief_graph"]
        tl = components["task_library"]
        all_beliefs = bg.query_all()
        if len(all_beliefs) < 2:
            return "信念数量不足，请先完成更多任务或导入数据。"
        contras = cd.full_scan(all_beliefs)
        if not contras:
            return "未发现信念矛盾。信念体系一致性良好。"
        new_tasks = cd.generate_probe_tasks(contras, tl)
        lines = [f"### 发现 {len(contras)} 组矛盾\n"]
        for i, c in enumerate(contras, 1):
            lines.append(f"**{i}. [{c.get('type', '')}]** {c.get('explanation', '')}")
            if c.get("resolution_hint"):
                lines.append(f"   可能解释: {c['resolution_hint']}")
            if c.get("probe_question"):
                lines.append(f"   验证问题: _{c['probe_question']}_")
            lines.append("")
        if new_tasks:
            lines.append(f"*已自动生成 {len(new_tasks)} 个追问任务，点「开始校准」获取*")
        return "\n".join(lines)

    from src.cognitive.task_library import TASK_DIMENSIONS

    next_task_btn.click(
        fn=_next_task,
        outputs=[task_display, task_current_id, task_current_prompt, task_progress_html],
    )
    submit_task_btn.click(
        fn=_submit_task,
        inputs=[task_current_id, task_current_prompt, task_response],
        outputs=[task_analysis_output, task_progress_html, task_display, task_current_id, task_current_prompt, task_response],
    )
    scan_contradictions_btn.click(fn=_scan_contradictions, outputs=contradiction_output)

    if demo is not None:
        demo.load(fn=_task_progress_html, outputs=task_progress_html)

    # ================================================================
    # Tab: Analytics Dashboard
    # ================================================================
