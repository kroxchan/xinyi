"""Tab: tab_system — extracted from app.py"""
from __future__ import annotations

def render_tab_system(components=None):
    info_output = gr.Textbox(label="系统状态", lines=12, interactive=False, show_copy_button=True)
    refresh_btn = gr.Button("刷新", variant="secondary")
    refresh_btn.click(fn=get_system_info, outputs=info_output)
    demo.load(fn=get_system_info, outputs=info_output)

    gr.Markdown("---\n### API 配置")
    gr.Markdown("修改后保存到 `config.yaml`，需重启生效。")
    with gr.Row():
        sys_api_provider = gr.Dropdown(
            label="Provider", choices=["openai", "anthropic", "gemini"],
            value=_pv, scale=1,
        )
        sys_api_model = gr.Textbox(label="Model", value=_md, scale=2)
    with gr.Row():
        sys_api_key = gr.Textbox(label="API Key", value=_ak, type="password", scale=3)
    with gr.Row():
        sys_api_base = gr.Textbox(label="Base URL（留空用默认）", value=_bu, scale=3)
    sys_save_api_btn = gr.Button("保存 API 配置", variant="primary")
    sys_save_api_result = gr.HTML()
    sys_save_api_btn.click(
        fn=_save_api,
        inputs=[sys_api_provider, sys_api_model, sys_api_key, sys_api_base],
        outputs=sys_save_api_result,
    )

    gr.Markdown("---\n### 重置学习数据")
    gr.Markdown("清除所有学习数据后可重新开始。")
    reset_all_btn = gr.Button("一键重置所有学习数据", variant="stop")
    reset_all_result = gr.HTML()

    def _reset_all_training():
        removed = []
        for p in [
            "data/persona_profile.yaml", "data/emotion_profile.yaml",
            "data/emotion_boundaries.json", "data/emotion_expression.json",
            "data/thinking_model.txt", "data/cognitive_profile.json",
            "data/beliefs.json", "data/memories.json",
            "data/contact_registry.json", "data/task_results.json",
        ]:
            fp = Path(p)
            if fp.exists():
                fp.unlink()
                removed.append(fp.name)
        import shutil
        chroma = Path("data/chroma_db")
        if chroma.exists():
            shutil.rmtree(chroma, ignore_errors=True)
            removed.append("chroma_db/")
        guidance = Path("data/guidance")
        if guidance.exists():
            for gf in guidance.glob("*.md"):
                gf.unlink()
                removed.append("guidance/" + gf.name)
        Path("data/task_results.json").write_text('{"completed": {}}', encoding="utf-8")
        if not removed:
            return '<span style="color:#a8969a">没有需要清除的数据。</span>'
        return '<span style="color:#65a88a">✓ 已清除：{}</span>'.format(", ".join(removed))

    reset_all_btn.click(fn=_reset_all_training, outputs=reset_all_result)

