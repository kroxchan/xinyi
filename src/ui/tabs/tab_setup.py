"""Tab: tab_setup — extracted from app.py"""
from __future__ import annotations

from src.features.local_model import LocalModelPresets

def render_tab_setup(components=None):

    gr.Markdown("### 连接你的 AI 服务")

    # -- status overview (refreshed after decrypt via decrypt_timer) --
    setup1_status = gr.HTML(value=_setup1_status_html())

    # -- API config --
    gr.Markdown("---\n#### API 配置")
    if _has_api:
        gr.Markdown(
            '<span style="color:#65a88a">✓ API 已配置完成。如需修改，可在「设置」中操作。</span>'
        )
    else:
        gr.Markdown("填写大模型 API 信息后保存。")
    with gr.Row():
        api_provider_input = gr.Dropdown(
            label="Provider", choices=["openai", "anthropic", "gemini"],
            value=_pv, scale=1, interactive=not _has_api,
        )
        api_model_input = gr.Textbox(label="Model", value=_md, scale=2, interactive=not _has_api)
    with gr.Row():
        api_key_input = gr.Textbox(label="API Key", value=_ak, type="password", scale=3, interactive=not _has_api)
    with gr.Row():
        api_base_input = gr.Textbox(label="Base URL（留空用默认）", value=_bu, scale=3, interactive=not _has_api)
    if not _has_api:
        save_api_btn = gr.Button("保存 API 配置", variant="primary")
        save_api_result = gr.HTML()
        save_api_btn.click(
            fn=_save_api,
            inputs=[api_provider_input, api_model_input, api_key_input, api_base_input],
            outputs=save_api_result,
        )

    # -- local model config (privacy-first) --
    gr.Markdown("---\n#### 🤖 本地模型（隐私优先）")
    gr.HTML(
        '<div style="font-size:12px;color:#8c7b7f;margin-bottom:12px">'
        "如果你有 Ollama、LM Studio 等本地模型，可以在这里一键配置，"
        "无需使用云端 API，聊天数据完全保存在本地。"
        "</div>"
    )

    local_preset_dropdown = gr.Dropdown(
        label="选择本地模型平台",
        choices=LocalModelPresets.get_preset_choices(),
        value="none",
        elem_id="local-preset-dropdown",
    )

    with gr.Row(visible=False) as local_model_row:
        local_model_input = gr.Dropdown(
            label="选择模型",
            elem_id="local-model-input",
            interactive=True,
        )
        local_base_url_input = gr.Textbox(
            label="Base URL（如需修改）",
            placeholder="通常不需要修改，使用默认值即可",
            elem_id="local-base-url-input",
        )

    local_check_btn = gr.Button("🔍 检查连接", variant="secondary", size="sm", visible=False)
    local_check_result = gr.HTML(value="", visible=False)

    local_apply_btn = gr.Button("✅ 应用本地模型配置", variant="primary", visible=False)
    local_apply_result = gr.HTML(value="")

    # -- local model event handlers --
    def _on_preset_change(preset_id: str):
        """当选择预设时，更新模型选项和可见性。"""
        if preset_id == "none":
            return (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                "",
            )
        preset = LocalModelPresets.get_preset(preset_id)
        if not preset:
            return (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                "",
            )
        model_choices = LocalModelPresets.get_model_choices(preset_id)
        default_model = LocalModelPresets.get_default_model(preset_id)
        default_base = LocalModelPresets.get_default_base_url(preset_id)
        return (
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(choices=model_choices, value=default_model),
            "",
        )

    def _on_check_connection(preset_id: str, model_id: str, base_url: str):
        """检查本地模型连接状态。"""
        if preset_id == "none":
            return ""
        if preset_id == "oneapi" and not base_url:
            return '<span style="color:#fbbf24">OneAPI 需要填写 Base URL 后再检查。</span>'
        preset = LocalModelPresets.get_preset(preset_id)
        check_url = preset.get("check_url") if preset else None
        if not check_url:
            return '<span style="color:#fbbf24">此平台不支持自动检查，请手动确认。</span>'
        url = base_url or preset.get("base_url", "") if preset else ""
        if not url:
            return '<span style="color:#f87171">请填写 Base URL。</span>'
        ok, msg = LocalModelPresets.check_connection(url)
        color = "#65a88a" if ok else "#f87171"
        icon = "✅" if ok else "❌"
        return f'<span style="color:{color}">{icon} {msg}</span>'

    def _on_apply_local(preset_id: str, model_id: str, base_url: str):
        """应用本地模型配置。"""
        if preset_id == "none":
            return '<span style="color:#8c7b7f">已保持云端API配置不变。</span>'
        preset = LocalModelPresets.get_preset(preset_id)
        if not preset:
            return '<span style="color:#f87171">未知预设。</span>'
        final_base = base_url or preset.get("base_url", "")
        if not final_base:
            return '<span style="color:#f87171">请填写 Base URL。</span>'
        if model_id == "custom":
            return '<span style="color:#fbbf24">请选择或输入具体模型名称。</span>'
        config = LocalModelPresets.format_config(preset_id, model_id, final_base)
        return (
            f'<span style="color:#65a88a">✅ 配置已应用！</span><br>'
            f'<code>provider</code>: {config["provider"]}<br>'
            f'<code>base_url</code>: {config["base_url"]}<br>'
            f'<code>model</code>: {config["model"]}<br>'
            '<span style="color:#8c7b7f;font-size:12px">切换到「对话」Tab 开始使用。</span>'
        )

    # 事件绑定
    local_preset_dropdown.change(
        fn=_on_preset_change,
        inputs=local_preset_dropdown,
        outputs=[
            local_model_row,
            local_base_url_input,
            local_check_btn,
            local_base_url_input,
            local_model_input,
            local_check_result,
        ],
    )
    local_check_btn.click(
        fn=_on_check_connection,
        inputs=[local_preset_dropdown, local_model_input, local_base_url_input],
        outputs=local_check_result,
    )
    local_apply_btn.click(
        fn=_on_apply_local,
        inputs=[local_preset_dropdown, local_model_input, local_base_url_input],
        outputs=local_apply_result,
    )

    # -- decrypt tool + keys --
    gr.Markdown("---\n#### 解密工具准备")
    if init_status["has_scanner"]:
        gr.HTML('<span style="color:#65a88a">✓ 解密工具已就绪。</span>')
    else:
        gr.HTML(STEP1_GUIDE_HTML)
    step1_btn = gr.Button(
        "✓ 已准备" if init_status["has_scanner"] else "自动准备解密工具",
        variant="secondary" if init_status["has_scanner"] else "primary",
        interactive=not init_status["has_scanner"],
    )
    step1_output = gr.HTML()

    gr.Markdown("---\n#### 提取密钥")
    repo_dir = Path("vendor/wechat-decrypt").resolve()
    if init_status["has_keys"]:
        gr.HTML('<span style="color:#65a88a">✓ 密钥已提取（{} 个）。</span>'.format(init_status.get("key_count", 0)))
    else:
        gr.HTML(_build_step2_guide_html(str(repo_dir)))
    gr.HTML(
        "<div style='font-size:0.82em;opacity:0.88;line-height:1.65;margin:8px 0 0;color:var(--body-text-color)'>"
        "<strong>说明：</strong>若 <code>all_keys.json</code> 里缺少 <code>message/message_0.db</code> 等主消息库密钥，"
        "私聊无法解密，扫描联系人可能为 0。请保持微信<strong>已登录并运行</strong>后，点「重新提取密钥」查看终端命令，"
        "再点「重新检测密钥」，必要时在第 3 步重新解密。"
        "</div>"
    )
    with gr.Row():
        step2_btn = gr.Button(
            "重新检测密钥" if init_status["has_keys"] else "检测密钥",
            variant="primary" if not init_status["has_keys"] else "secondary",
        )
        step2_reextract_btn = gr.Button("重新提取密钥", variant="secondary")
    step2_output = gr.HTML()

    gr.Markdown("---\n#### 解密数据库")
    step3_decrypt_banner = gr.HTML(value=_step3_decrypt_banner_html())
    gr.HTML(
        "<div style='font-size:0.82em;opacity:0.88;line-height:1.65;margin:8px 0 0'>"
        "重新提取密钥或更换数据源后，可随时点「重新解密」覆盖 <code>data/raw</code> 下的解密结果。"
        "</div>"
    )
    step3_btn = gr.Button(
        "重新解密" if _has_decrypted else "开始解密",
        variant="secondary" if _has_decrypted else "primary",
        size="lg",
    )
    step3_output = gr.HTML()

    with gr.Accordion("高级：已有解密数据库？直接导入", open=False):
        with gr.Row():
            path_input = gr.Textbox(
                label="解密目录路径",
                placeholder="例如: /path/to/wechat-decrypt/decrypted",
                scale=5,
            )
            link_btn = gr.Button("导入目录", variant="primary", scale=1)
        scan_info = gr.Textbox(label="扫描结果", interactive=False, lines=2)
        link_result = gr.HTML()

    if _has_decrypted or _has_api:
        gr.Markdown(
            '\n<div style="text-align:center;margin-top:16px">'
            '<span style="font-size:1.1em">完成后，前往 <b>「选择 TA」</b> →</span>'
            '</div>'
        )

    decrypt_timer = gr.Timer(value=3, active=False)

    def _decrypt_poll():
        r = TrainingRunner.instance()
        steps = r.get_steps()
        active = r.is_running() and not r.done
        skip = gr.update()
        st_up = skip
        ban_up = skip
        if not steps:
            return skip, skip, gr.Timer(active=active), st_up, ban_up
        html = _step_html(steps)
        if r.mode == "step1":
            return html, skip, gr.Timer(active=active), st_up, ban_up
        if r.mode == "step3":
            out3 = html
            if r.done:
                st_up = _setup1_status_html()
                ban_up = _step3_decrypt_banner_html()
            return skip, out3, gr.Timer(active=active), st_up, ban_up
        return skip, skip, gr.Timer(active=active), st_up, ban_up

    decrypt_timer.tick(
        fn=_decrypt_poll,
        outputs=[step1_output, step3_output, decrypt_timer, setup1_status, step3_decrypt_banner],
    )

    step1_btn.click(fn=run_step1_prepare, outputs=[step1_output, decrypt_timer])
    step2_btn.click(fn=run_step2_check_keys, outputs=step2_output)
    step2_reextract_btn.click(fn=run_step2_reextract_instructions, outputs=step2_output)
    step3_btn.click(fn=run_step3_decrypt_only, outputs=[step3_output, decrypt_timer])
    def _link_external_dir_ui(path_str: str):
        h, s = link_external_dir(path_str)
        return h, s, _setup1_status_html(), _step3_decrypt_banner_html()

    link_btn.click(
        fn=_link_external_dir_ui,
        inputs=path_input,
        outputs=[link_result, scan_info, setup1_status, step3_decrypt_banner],
    )
    path_input.submit(
        fn=_link_external_dir_ui,
        inputs=path_input,
        outputs=[link_result, scan_info, setup1_status, step3_decrypt_banner],
    )

    # ================================================================
    # Setup Tab 2: 联系人与对象
    # ================================================================
