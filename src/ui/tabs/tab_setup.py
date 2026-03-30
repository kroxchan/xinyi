"""Tab: tab_setup — extracted from app.py"""
from __future__ import annotations

import gradio as gr
from pathlib import Path

from src.features.local_model import LocalModelPresets
from src.ui.callbacks_api import (
    save_api,
    load_api_fields,
    run_step1_prepare,
    run_step2_check_keys,
    run_step2_reextract_instructions,
    run_step3_decrypt_only,
    link_external_dir,
    step_done_html,
    setup1_status_html,
    step3_decrypt_banner_html,
    _build_step2_guide_html,
    STEP1_GUIDE_HTML,
)
from src.ui.shared import _step_html
from src.ui.ux_helpers import UXHelper, StatusLevel


def _lazy_from_app(name: str):
    """Lazy import from src.app to avoid circular dependency at import time."""
    import src.app as _m
    return getattr(_m, name)


def render_tab_setup(
    components=None,
    *,
    _has_api: bool,
    _pv: str,
    _md: str,
    _ak: str,
    _bu: str,
    init_status: dict,
    _has_decrypted: bool,
    is_ready: bool = False,
    demo=None,
) -> dict:
    """Returns dict with references to output components for event wiring."""

    # --- Setup Wizard 进度指示器 ---
    _ak2, _bu2, _md2, _pv2 = load_api_fields()
    _has_api2 = bool(_ak2)

    setup_wizard_html = gr.HTML(
        value=UXHelper.format_setup_progress([
            {"name": "API 配置", "done": _has_api2, "active": not _has_api2},
            {"name": "解密数据", "done": _has_decrypted, "active": _has_api2 and not _has_decrypted},
            {"name": "训练",    "done": is_ready,       "active": _has_api2 and _has_decrypted and not is_ready},
        ])
    )

    # === 错误恢复引导（新增）===
    gr.HTML(
        '<div id="setup-recovery-guide" style="display:none;margin:12px 0"></div>'
    )

    # 上下文感知的错误恢复折叠区
    with gr.Accordion("🆘 遇到问题了？查看解决方案", open=False, elem_id="setup-recovery-accordion"):
        _recovery_html = _build_recovery_guide_html(
            has_api=bool(_ak2),
            has_scanner=init_status.get("has_scanner", False),
            has_keys=init_status.get("has_keys", False),
            has_decrypted=init_status.get("has_decrypted", False),
            is_ready=is_ready,
        )
        gr.HTML(value=_recovery_html)

    def _build_recovery_guide_html(
        has_api: bool,
        has_scanner: bool,
        has_keys: bool,
        has_decrypted: bool,
        is_ready: bool,
    ) -> str:
        """根据当前 pipeline 状态，生成上下文感知的错误恢复指南。"""
        sections = []

        if not has_api:
            sections.append({
                "title": "1️⃣ API 配置问题",
                "icon": "🔑",
                "color": "#dc2626",
                "bg": "#fee2e2",
                "items": [
                    ("无法获取 API Key", "前往 OpenAI / Anthropic 官网申请 API Key，免费额度即可使用"),
                    ("API Key 报错 401/403", "检查 Key 是否复制完整，前后无空格；确认账户有可用额度"),
                    ("API Key 报错 429", "请求频率超限，稍等 1-2 分钟后再试，或升级付费套餐"),
                    ("模型不支持", "推荐使用 gpt-4o-mini 或 gpt-4o，兼容性好"),
                ],
            })

        if not has_scanner:
            sections.append({
                "title": "2️⃣ 解密工具问题（macOS）",
                "icon": "🔧",
                "color": "#d97706",
                "bg": "#fef3c7",
                "items": [
                    ("提示 'task_for_pid failed'", "这是 macOS 安全限制，需关闭 SIP 调试限制后重试；详见上方「获取访问权限」卡片中的步骤"),
                    ("提示 'Operation not permitted'", "在「系统设置 → 隐私与安全 → 安全性与隐私」中允许 Python 访问"),
                    ("提示 'Xcode not found'", "运行：xcode-select --install 安装 Xcode 命令行工具"),
                    ("编译失败", "确保 macOS 版本 ≥ 10.14，Python 版本 ≥ 3.9"),
                ],
            })

        if has_scanner and not has_keys:
            sections.append({
                "title": "3️⃣ 密钥提取问题",
                "icon": "🔐",
                "color": "#d97706",
                "bg": "#fef3c7",
                "items": [
                    ("找不到密钥 / 密钥数量为 0", "确保微信已登录并运行；私聊需要有实际消息往来才能提取密钥"),
                    ("只有群聊密钥，私聊无法解密", "私聊需要有至少 1 条消息；跟对方发一条消息后再提取密钥"),
                    ("重新提取后密钥消失", "部分密钥为临时会话密钥，建议保持微信一直运行"),
                ],
            })

        if has_keys and not has_decrypted:
            sections.append({
                "title": "4️⃣ 数据库解密问题",
                "icon": "📂",
                "color": "#7c3aed",
                "bg": "#ede9fe",
                "items": [
                    ("解密失败 / 0 个数据库", "请在「设置 → 系统」中查看详细错误信息；尝试重新提取密钥"),
                    ("数据库被占用", "确保微信已关闭，或使用「导入已有解密目录」功能"),
                    ("解密很慢", "正常，macOS 上可能需要 5-10 分钟；耐心等待即可"),
                ],
            })

        if has_decrypted and not is_ready:
            sections.append({
                "title": "5️⃣ 训练/学习问题",
                "icon": "🤖",
                "color": "#0891b2",
                "bg": "#ecfeff",
                "items": [
                    ("训练中断 / 页面刷新", "数据保存在本地，重新进入会自动恢复；终端可见详细日志"),
                    ("人格不像 TA", "建议训练 100+ 条真实对话；可在「对话」Tab 使用「不像 TA？」反馈改进"),
                    ("对话数量太少", "至少需要 30 条消息；越多训练效果越好"),
                ],
            })

        sections.append({
            "title": "💡 通用问题",
            "icon": "🔎",
            "color": "#475569",
            "bg": "#f1f5f9",
            "items": [
                ("页面卡住 / 无响应", "尝试刷新页面（Cmd/Ctrl+R）；重启应用"),
                ("找不到配置文件", "在项目根目录查找 config.yaml；不存在时自动使用默认配置"),
                ("端口被占用", "其他进程占用了 7872 端口；修改 app.py 中的 server_port 或关闭冲突进程"),
                ("需要更多帮助", "查看项目根目录的 INSTALL.md 文档，或在终端查看详细错误日志"),
            ],
        })

        html = '<div style="display:flex;flex-direction:column;gap:16px;padding:4px 0">'
        for sec in sections:
            items_html = ""
            for title, detail in sec["items"]:
                items_html += (
                    f'<div style="margin-bottom:10px;padding:8px 10px;background:white;border-radius:6px">'
                    f'<div style="font-weight:600;font-size:.85em;color:{sec["color"]};margin-bottom:3px">'
                    f'❓ {title}</div>'
                    f'<div style="font-size:.82em;color:#4a4a4a;line-height:1.5">{detail}</div>'
                    f'</div>'
                )
            html += (
                f'<div style="padding:14px 16px;background:{sec["bg"]};border-radius:10px">'
                f'<div style="font-weight:700;font-size:.9em;color:{sec["color"]};margin-bottom:12px">'
                f'{sec["icon"]} {sec["title"]}</div>'
                f'{items_html}'
                f'</div>'
            )
        html += '</div>'
        return html

    gr.Markdown("### 连接你的 AI 服务")

    # -- status overview (refreshed after decrypt via decrypt_timer) --
    setup1_status = gr.HTML(value=setup1_status_html())

    # -- API config -- always editable so users can update keys/models
    gr.Markdown("---\n#### API 配置")
    gr.Markdown("填写大模型 API 信息后保存。已配置时可直接修改并重新保存。")
    with gr.Row():
        api_provider_input = gr.Dropdown(
            label="Provider", choices=["openai", "anthropic", "gemini"],
            value=_pv, scale=1, interactive=True,
        )
        api_model_input = gr.Textbox(label="Model", value=_md, scale=2, interactive=True)
    with gr.Row():
        api_key_input = gr.Textbox(label="API Key", value=_ak, type="password", scale=3, interactive=True)
    with gr.Row():
        api_base_input = gr.Textbox(label="Base URL（留空用默认）", value=_bu, scale=3, interactive=True)

    save_api_btn = gr.Button("保存 API 配置", variant="primary")
    save_api_result = gr.HTML()

    def _save_api_with_wizard(pv, md, ak, bu):
        msg = save_api(pv, md, ak, bu)
        wizard = UXHelper.format_setup_progress([
            {"name": "API 配置", "done": bool(ak), "active": not bool(ak)},
            {"name": "解密数据", "done": _has_decrypted, "active": bool(ak) and not _has_decrypted},
            {"name": "训练",    "done": is_ready,       "active": bool(ak) and _has_decrypted and not is_ready},
        ])
        return msg, wizard

    save_api_btn.click(
        fn=_save_api_with_wizard,
        inputs=[api_provider_input, api_model_input, api_key_input, api_base_input],
        outputs=[save_api_result, setup_wizard_html],
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
    step3_decrypt_banner = gr.HTML(value=step3_decrypt_banner_html())
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

    # 轮询通过 demo.load(fn=..., every=3) 实现，不使用 gr.Timer 组件
    # 原因：gr.Timer 作为 output 被替换时，tick 注册的实例也随之失效，无法激活定时器

    step1_btn.click(fn=run_step1_prepare, outputs=[step1_output])
    step2_btn.click(fn=run_step2_check_keys, outputs=step2_output)
    step2_reextract_btn.click(fn=run_step2_reextract_instructions, outputs=step2_output)
    step3_btn.click(fn=run_step3_decrypt_only, outputs=[step3_output])

    def _link_external_dir_ui(path_str: str):
        h, s = link_external_dir(path_str)
        return h, s, gr.update()   # placeholder: keeps outputs=[link_result, scan_info, setup1_status] correct

    link_btn.click(
        fn=_link_external_dir_ui,
        inputs=path_input,
        outputs=[link_result, scan_info, setup1_status],
    )
    path_input.submit(
        fn=_link_external_dir_ui,
        inputs=path_input,
        outputs=[link_result, scan_info, setup1_status],
    )

    # ================================================================
    # Setup Tab 2: 联系人与对象
    # ================================================================
    gr.Markdown("### 告诉心译，TA 是谁")

    from src.data.partner_config import load_partner_wxid as _lpw
    _cur_partner = _lpw().strip()

    _has_partner = init_status.get("has_partner", False)

    # Lazily resolve functions from src.app to avoid circular import
    _build_contact_registry_callback = _lazy_from_app("build_contact_registry_callback")
    _partner_candidate_choices = _lazy_from_app("partner_candidate_choices")
    _save_partner_selection = _lazy_from_app("save_partner_selection")
    _save_twin_mode_selection = _lazy_from_app("save_twin_mode_selection")
    _current_twin_mode = _lazy_from_app("_current_twin_mode")
    _import_data = _lazy_from_app("import_data")
    _detect_pipeline_status = _lazy_from_app("_detect_pipeline_status")
    _TrainingRunner = _lazy_from_app("TrainingRunner")

    setup2_status = gr.HTML(value=(
        step_done_html("对象已确认", _has_partner, _cur_partner if _has_partner else "未选择") + "<br>"
        + step_done_html("训练模式", True, "训练{}的分身".format(
            "自己" if _current_twin_mode() == "self" else "对象"
        ))
    ))

    gr.Markdown("---\n#### 扫描联系人")
    if _has_partner:
        gr.HTML('<span style="color:#65a88a">✓ 对象已确认：<b>{}</b>。如需更换，请重新扫描。</span>'.format(_cur_partner))

    def _partner_scan_only():
        msg, _tbl, _dd = _build_contact_registry_callback()
        return msg, gr.update(choices=_partner_candidate_choices())

    scan_partner_btn = gr.Button("扫描联系人", variant="primary")
    scan_partner_html = gr.HTML()
    partner_pick = gr.Dropdown(
        label="选择对象",
        choices=_partner_candidate_choices(),
        interactive=True,
        allow_custom_value=False,
    )
    save_partner_btn = gr.Button("保存为我的对象", variant="primary")
    save_partner_html = gr.HTML()

    scan_partner_btn.click(
        fn=_partner_scan_only,
        outputs=[scan_partner_html, partner_pick],
    )
    save_partner_btn.click(
        fn=_save_partner_selection,
        inputs=[partner_pick],
        outputs=[save_partner_html, partner_pick],
    )

    gr.Markdown("---\n#### 训练模式")
    gr.Markdown(
        "- **训练自己**：学你的说话风格，生成你的分身（对象跟「你」聊）\n"
        "- **训练对象**：学对象的说话风格，生成 TA 的分身（你跟「TA」聊）\n\n"
        "如果两个都要，先训练一个，再克隆项目另起一个 Dashboard。"
    )
    twin_mode_radio = gr.Radio(
        choices=[("训练自己的分身", "self"), ("训练对象的分身", "partner")],
        value=_current_twin_mode(),
        label="训练模式",
    )
    twin_mode_html = gr.HTML()
    twin_mode_radio.change(
        fn=_save_twin_mode_selection,
        inputs=[twin_mode_radio],
        outputs=[twin_mode_html],
    )

    gr.Markdown("---\n#### 开始学习")
    gr.Markdown("确认对象和训练模式后，点击开始。")

    if is_ready:
        gr.Markdown(
            '<div style="padding:16px;background:#065f46;border-radius:10px;text-align:center;margin:12px 0">'
            '<span style="color:#6ee7b7;font-size:1.2em;font-weight:600">✅ 学习完成！所有功能已解锁。</span>'
            '</div>'
        )

    train_btn = gr.Button(
        "重新学习" if is_ready else "开始学习",
        variant="primary",
        size="lg",
    )
    train_output = gr.Textbox(label="学习进度", lines=12, interactive=False, show_copy_button=True)

    # 注意：不再用 gr.Timer 作为 output 组件（Gradio 会替换实例导致 tick 失效）
    # 轮询统一通过 app.py 的 demo.load(fn=..., every=3) 实现

    # train_btn 只更新进度文字，定时轮询由 app.py demo.load(fn=..., every=3) 统一处理
    train_btn.click(fn=_import_data, outputs=[train_output])

    return {
        "train_output": train_output,
        "step1_output": step1_output,
        "step3_output": step3_output,
        "setup1_status": setup1_status,
        "step3_decrypt_banner": step3_decrypt_banner,
        "setup_wizard_html": setup_wizard_html,
    }
