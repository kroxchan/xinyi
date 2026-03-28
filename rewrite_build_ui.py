#!/usr/bin/env python3
"""Script to rewrite build_ui() in app.py with the new tab structure."""

import re

APP_PATH = "src/app.py"

# Read the original file
with open(APP_PATH, "r") as f:
    content = f.read()

# Find the build_ui function boundaries
build_ui_pattern = r'(def build_ui\(\) -> gr\.Blocks:.*?)(\n\nif __name__ == "__main__":)'

match = re.search(build_ui_pattern, content, re.DOTALL)
if not match:
    print("ERROR: Could not find build_ui function")
    exit(1)

build_ui_start = match.start(1)
build_ui_end = match.end(1)
after_build_ui = match.group(2)

# Extract the imports and class/function definitions that come AFTER build_ui
# (in this case, nothing substantive - the if __name__ block comes right after)

# Create the new build_ui function
new_build_ui = '''def build_ui() -> gr.Blocks:
    # Configure structured logging
    from src.logging_config import setup_logging
    setup_logging()

    with gr.Blocks(
        theme=gr.themes.Soft(
            primary_hue=gr.themes.colors.rose,
            secondary_hue=gr.themes.colors.amber,
            neutral_hue=gr.themes.colors.stone,
            font=[gr.themes.GoogleFont("Inter"), gr.themes.GoogleFont("Noto Sans SC"),
                  "ui-sans-serif", "system-ui", "sans-serif"],
            font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
        ).set(
            body_background_fill="#faf7f5",
            body_background_fill_dark="#1a1617",
            block_background_fill="#ffffff",
            block_background_fill_dark="#262122",
            block_border_color="#e6dcd8",
            block_border_color_dark="#3a3234",
            border_color_primary="#e6dcd8",
            input_background_fill="#ffffff",
            input_background_fill_dark="#2c2627",
            button_primary_background_fill="#b07c84",
            button_primary_background_fill_hover="#9a6a73",
            button_primary_text_color="#ffffff",
            shadow_drop="0 1px 3px rgba(61,44,48,0.06)",
            shadow_drop_lg="0 4px 12px rgba(61,44,48,0.08)",
        ),
        title="心译",
        css=CUSTOM_CSS,
    ) as demo:
        if init_error:
            gr.Markdown(
                f"> **初始化警告**: {init_error}\\n>\\n"
                f"> 请检查 `config.yaml` 配置后重启。"
            )

        init_status = _detect_pipeline_status()
        is_ready = init_status["has_training"]

        def _load_api_fields():
            try:
                resolved = load_config()
                api = resolved.get("api", {})
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                api_raw = raw.get("api", {})
                return (
                    api.get("api_key", "") or api_raw.get("api_key", ""),
                    str(api.get("base_url") or api_raw.get("base_url") or ""),
                    api.get("model", "") or api_raw.get("model", ""),
                    api.get("provider", "openai") or api_raw.get("provider", "openai"),
                )
            except Exception:
                return "", "", "", "openai"

        def _save_api(provider, model, key, base_url):
            if not (key or "").strip():
                return '<span style="color:#f87171">API Key 不能为空</span>'
            try:
                cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8")) or {}
            except Exception:
                cfg = {}
            if "api" not in cfg:
                cfg["api"] = {}
            cfg["api"]["provider"] = (provider or "openai").strip()
            model_stripped = (model or "").strip()
            cfg["api"]["model"] = model_stripped
            cfg["api"]["extraction_model"] = model_stripped
            cfg["api"]["api_key"] = (key or "").strip()
            cfg["api"]["base_url"] = (base_url or "").strip() or None
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

            global components, init_error, contact_registry, session_mgr, persona_mgr
            try:
                _cfg = load_config()
                components = init_components(_cfg)
                from src.engine.advisor_registry import get_registry as _gr
                _gr().reload()
                from src.engine.session import SessionManager
                session_mgr = SessionManager(directory="data/sessions")
                from src.engine.persona import PersonaManager
                persona_mgr = PersonaManager(directory="data/personas")
                from src.data.contact_registry import ContactRegistry
                contact_registry = ContactRegistry()
                ensure_couple_personas()
                import threading
                threading.Thread(target=components["embedder"].warmup, daemon=True).start()
                init_error = None
                logger.info("API 配置保存后重新初始化成功")
                return '<span style="color:#65a88a">✓ 已保存并初始化完成，可以开始使用。</span>'
            except Exception as e:
                init_error = str(e)
                logger.error("API 保存后重新初始化失败: %s", e)
                return f'<span style="color:#65a88a">✓ 已保存。</span><span style="color:#f59e0b"> 初始化失败（{e}），请检查配置后刷新页面。</span>'

        _ak, _bu, _md, _pv = _load_api_fields()
        _has_api = bool(_ak)
        _has_partner = init_status.get("has_partner", False)
        _has_decrypted = init_status.get("has_decrypted", False)

        def _step_done_html(label, done, detail=""):
            icon = "✅" if done else "⬜"
            d = f' <span style="opacity:.6">— {detail}</span>' if detail else ""
            return f'<span style="font-size:.95em">{icon} {label}{d}</span>'

        def _setup1_status_html():
            st = _detect_pipeline_status()
            ak2, bu2, md2, pv2 = _load_api_fields()
            has_api2 = bool(ak2)
            hd = st.get("has_decrypted", False)
            return (
                _step_done_html("API 已配置", has_api2, pv2 + " / " + md2 if has_api2 else "未配置") + "<br>"
                + _step_done_html("解密工具", st["has_scanner"], "已编译" if st["has_scanner"] else "") + "<br>"
                + _step_done_html("密钥提取", st["has_keys"], "{} 个密钥".format(st.get("key_count", 0)) if st["has_keys"] else "") + "<br>"
                + _step_done_html("数据库解密", hd, "{} 个数据库".format(st.get("db_count", 0)) if hd else "")
            )

        def _step3_decrypt_banner_html():
            st = _detect_pipeline_status()
            if st.get("has_decrypted"):
                return '<span style="color:#65a88a">✓ 数据库已解密（{} 个）。</span>'.format(st.get("db_count", 0))
            return STEP3_GUIDE_HTML

        def _build_step2_guide_html(repo_dir):
            return (
                '<div style="padding:12px 16px;background:#1e181b;border-radius:8px;font-size:.85em">'
                '<p style="margin:0 0 8px"><b>步骤：</b></p>'
                '<ol style="margin:0;padding-left:18px;line-height:1.9">'
                '<li>终端运行：<code>cd ' + repo_dir + ' && python scanner.py</code></li>'
                '<li>确保微信 PC 版已<strong>登录并打开聊天窗口</strong></li>'
                '<li>点击「重新检测密钥」验证</li>'
                '</ol>'
                '</div>'
            )

        # ====================================================================
        # Import and render each Tab
        # ====================================================================
        from src.ui.tabs.tab_setup import render_setup_tabs
        from src.ui.tabs.tab_chat import render_chat_tab
        from src.ui.tabs.tab_eval import render_eval_tab
        from src.ui.tabs.tab_cognitive import render_cognitive_tab
        from src.ui.tabs.tab_analytics import render_analytics_tab
        from src.ui.tabs.tab_beliefs import render_beliefs_tab
        from src.ui.tabs.tab_memories import render_memories_tab
        from src.ui.tabs.tab_system import render_system_tab
        from src.cognitive.task_library import TASK_DIMENSIONS

        with gr.Tabs(elem_id="main-tabs") as main_tabs:
            # === Setup Tabs (连接 + 选择TA) ===
            step1_output, step3_output, decrypt_timer, setup1_status, step3_decrypt_banner, train_output, progress_timer = render_setup_tabs(
                init_status=init_status,
                _has_api=_has_api,
                _has_partner=_has_partner,
                _has_decrypted=_has_decrypted,
                _pv=_pv,
                _md=_md,
                _ak=_ak,
                _bu=_bu,
                STEP1_GUIDE_HTML=STEP1_GUIDE_HTML,
                _build_step2_guide_html=_build_step2_guide_html,
                _step_html=_step_html,
                _step_done_html=_step_done_html,
                _setup1_status_html=_setup1_status_html,
                _step3_decrypt_banner_html=_step3_decrypt_banner_html,
                run_step1_prepare=run_step1_prepare,
                run_step2_check_keys=run_step2_check_keys,
                run_step2_reextract_instructions=run_step2_reextract_instructions,
                run_step3_decrypt_only=run_step3_decrypt_only,
                link_external_dir=link_external_dir,
                TrainingRunner=TrainingRunner,
                partner_candidate_choices=partner_candidate_choices,
                save_partner_selection=save_partner_selection,
                _current_twin_mode=_current_twin_mode,
                save_twin_mode_selection=save_twin_mode_selection,
                build_contact_registry_callback=build_contact_registry_callback,
            )

            # === Chat Tab ===
            tab_chat, chatbot, _adv_state = render_chat_tab(
                is_ready=is_ready,
                components=components,
                logger=logger,
                blocks=demo,
            )

            # === Evaluation Tab ===
            tab_eval, = render_eval_tab(
                is_ready=is_ready,
                components=components,
                logger=logger,
            )

            # === Cognitive Calibration Tab ===
            tab_cognitive, = render_cognitive_tab(
                is_ready=is_ready,
                components=components,
                TASK_DIMENSIONS=TASK_DIMENSIONS,
            )

            # === Analytics Tab ===
            tab_analytics, analytics_outputs = render_analytics_tab(
                is_ready=is_ready,
                load_analytics=load_analytics,
            )

            # === Beliefs Tab ===
            tab_beliefs, belief_table = render_beliefs_tab(
                is_ready=is_ready,
                query_beliefs=query_beliefs,
            )

            # === Memories Tab ===
            tab_memories, mem_table = render_memories_tab(
                is_ready=is_ready,
                components=components,
                query_memories=query_memories,
                edit_memory=edit_memory,
                delete_memory=delete_memory,
                add_memory_manual=add_memory_manual,
            )

            # === System Tab ===
            render_system_tab(
                _pv=_pv,
                _md=_md,
                _ak=_ak,
                _bu=_bu,
                _save_api=_save_api,
                get_system_info=get_system_info,
            )

        # ====================================================================
        # Wire timer & page-load to update training outputs and tab visibility
        # ====================================================================
        def _tab_vis():
            ready = _detect_pipeline_status()["has_training"]
            vis = gr.update(visible=True) if ready else gr.update()
            return [vis] * 6

        def _render_runner(r):
            steps = r.get_steps()
            active = r.is_running() and not r.done
            skip = gr.update()
            tab_updates = _tab_vis() if (r.done and not r.error) else [skip] * 6
            base = [skip, gr.Timer(active=active)]
            if not steps:
                return base + tab_updates
            if r.mode == "text":
                base[0] = "\\n".join(str(s) for s in steps)
            elif r.mode in ("step3", "step1"):
                base[0] = _step_html(steps)
            else:
                base[0] = "\\n".join(str(s) for s in steps)
            return base + tab_updates

        def _poll_tick():
            return _render_runner(TrainingRunner.instance())

        def _on_page_load():
            return _render_runner(TrainingRunner.instance())

        _all_timer_outputs = [
            train_output, progress_timer,
            tab_chat, tab_cognitive, tab_analytics, tab_beliefs, tab_memories, tab_eval,
        ]
        progress_timer.tick(fn=_poll_tick, outputs=_all_timer_outputs)
        demo.load(fn=_on_page_load, outputs=_all_timer_outputs)

        # Wire load events for analytics
        demo.load(fn=load_analytics, outputs=analytics_outputs)
        demo.load(fn=query_beliefs, inputs=[], outputs=[belief_table])
        demo.load(fn=query_memories, inputs=[""], outputs=[mem_table])

    return demo


'''

# Replace the build_ui function
new_content = content[:build_ui_start] + new_build_ui + "\n\n" + after_build_ui

# Write the new content
with open(APP_PATH, "w") as f:
    f.write(new_content)

print("Successfully rewrote build_ui() in app.py")
