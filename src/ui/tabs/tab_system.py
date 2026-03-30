"""Tab: tab_system — extracted from app.py"""
from __future__ import annotations

from pathlib import Path

import gradio as gr
from src.ui.callbacks_api import save_api_and_refresh
from src.ui.ux_helpers import UXHelper, StatusLevel


# ==============================================================================
# 连接状态检查函数
# ==============================================================================

def _check_api_status() -> dict:
    """检查 API 连接状态，返回 {status, detail}"""
    try:
        from src.ui.callbacks_api import load_api_fields
        ak, bu, md, pv = load_api_fields()
        if not ak:
            return {
                "status": StatusLevel.ERROR,
                "detail": "未配置 API Key",
                "action": "前往「设置」Tab 配置",
            }
        from openai import OpenAI
        import time as _check_time
        start = _check_time.time()
        client_kwargs = {"api_key": ak, "timeout": 8.0}
        if bu:
            client_kwargs["base_url"] = bu
        test_client = OpenAI(**client_kwargs)
        test_client.chat.completions.create(
            model=md or "gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=2,
        )
        elapsed_ms = int((_check_time.time() - start) * 1000)
        return {
            "status": StatusLevel.SUCCESS,
            "detail": f"{pv} / {md or '默认'} · {elapsed_ms}ms",
        }
    except Exception as e:
        err_str = str(e)
        if "401" in err_str or "403" in err_str or "unauthorized" in err_str.lower():
            detail = "认证失败：API Key 无效或已过期"
        elif "429" in err_str or "rate limit" in err_str.lower():
            detail = "频率超限：API 请求过多"
        elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
            detail = "连接超时：网络或服务问题"
        elif "connection" in err_str.lower():
            detail = "连接失败：检查网络或 Base URL"
        else:
            detail = err_str[:60] if err_str else "未知错误"
        return {"status": StatusLevel.ERROR, "detail": detail}


def _check_db_status() -> dict:
    """检查数据库状态"""
    from src.app import _detect_pipeline_status
    st = _detect_pipeline_status()
    if st.get("has_decrypted"):
        count = st.get("db_count", 0)
        return {"status": StatusLevel.SUCCESS, "detail": f"{count} 个数据库已解密"}
    if st.get("has_keys"):
        return {"status": StatusLevel.WARNING, "detail": "密钥已提取，尚未解密"}
    return {"status": StatusLevel.WARNING, "detail": "未解密"}


def _check_model_status() -> dict:
    """检查人格模型状态"""
    components = None
    try:
        from src import app as _app_module
        components = _app_module.components
    except Exception:
        pass
    if components is None:
        return {"status": StatusLevel.INFO, "detail": "系统未初始化"}
    persona_path = Path("data/persona_profile.yaml")
    if not persona_path.exists():
        return {"status": StatusLevel.WARNING, "detail": "尚未训练人格"}
    return {"status": StatusLevel.SUCCESS, "detail": "人格已构建"}


def _render_status_dashboard_html() -> str:
    """渲染完整状态仪表板 HTML"""
    api_st   = _check_api_status()
    db_st    = _check_db_status()
    model_st = _check_model_status()

    cards = [
        UXHelper.format_status_card("API", api_st["status"], api_st["detail"]),
        UXHelper.format_status_card("数据库", db_st["status"], db_st["detail"]),
        UXHelper.format_status_card("人格模型", model_st["status"], model_st["detail"]),
    ]

    has_error = any(s["status"] == StatusLevel.ERROR for s in [api_st, db_st, model_st])
    alert_html = ""
    if has_error:
        error_services = [n for n, s in [("API", api_st), ("数据库", db_st), ("人格模型", model_st)]
                          if s["status"] == StatusLevel.ERROR]
        alert_html = (
            f'<div style="padding:10px 14px;background:#fee2e2;border-radius:8px;'
            'border:1px solid #fca5a5;margin-bottom:12px;font-size:.85em;color:#991b1b">'
            f'⚠️ {", ".join(error_services)} 存在问题，建议先修复后再使用'
            '</div>'
        )

    return (
        (alert_html if has_error else "")
        + UXHelper.format_status_dashboard(cards)
        + '<div style="font-size:.75em;color:#8c7b7f;margin-top:8px;text-align:right">'
        '💡 每 10 秒自动刷新，或点击「刷新状态」手动更新'
        '</div>'
    )


# ==============================================================================
# Tab 渲染
# ==============================================================================

def render_tab_system(
    *, _pv: str, _md: str, _ak: str, _bu: str, demo=None
) -> dict:
    get_system_info = __import__("src.app", fromlist=["get_system_info"]).get_system_info

    # --- 连接状态仪表板 ---
    gr.Markdown("### 💻 系统状态")
    status_dashboard = gr.HTML(value=_render_status_dashboard_html(), elem_id="status-dashboard")

    with gr.Row():
        refresh_status_btn = gr.Button("🔄 刷新状态", variant="secondary", size="sm")
        info_output = gr.Textbox(
            label="详细信息", lines=8, interactive=False, show_copy_button=True
        )

    def _refresh_all():
        return _render_status_dashboard_html(), get_system_info()

    refresh_status_btn.click(fn=_refresh_all, outputs=[status_dashboard, info_output])

    if demo is not None:
        demo.load(fn=_refresh_all, outputs=[status_dashboard, info_output])

    gr.Markdown("---\n### API 配置")
    gr.Markdown("修改后点击保存，立即生效，无需重启。")
    with gr.Row():
        sys_api_provider = gr.Dropdown(
            label="Provider",
            choices=["openai", "anthropic", "gemini"],
            value=_pv,
            scale=1,
        )
        sys_api_model = gr.Textbox(label="Model", value=_md, scale=2)
    with gr.Row():
        sys_api_key = gr.Textbox(label="API Key", value=_ak, type="password", scale=3)
    with gr.Row():
        sys_api_base = gr.Textbox(label="Base URL（留空用默认）", value=_bu, scale=3)
    sys_save_api_btn = gr.Button("保存 API 配置", variant="primary")
    sys_save_api_result = gr.HTML()

    def _save_and_refresh(pv, md, ak, bu):
        from src.ui.callbacks_api import load_api_fields as _laf
        msg = save_api_and_refresh(pv, md, ak, bu)[0]
        dashboard = _render_status_dashboard_html()
        info = get_system_info()
        # 重新从磁盘读取，确保字段显示实际生效的值
        new_ak, new_bu, new_md, new_pv = _laf()
        return (
            msg,
            dashboard,
            info,
            gr.update(value=new_pv),
            gr.update(value=new_md),
            gr.update(value=new_ak),
            gr.update(value=new_bu),
        )

    sys_save_api_btn.click(
        fn=_save_and_refresh,
        inputs=[sys_api_provider, sys_api_model, sys_api_key, sys_api_base],
        outputs=[
            sys_save_api_result,
            status_dashboard,
            info_output,
            sys_api_provider,
            sys_api_model,
            sys_api_key,
            sys_api_base,
        ],
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
            return UXHelper.format_hint("没有需要清除的数据。")
        return (
            UXHelper.format_success(f"已清除：{', '.join(removed)}")
            + UXHelper.format_info("数据重置完成，可前往「设置」重新开始。")
        )

    reset_all_btn.click(fn=_reset_all_training, outputs=reset_all_result)

    return {"status_dashboard": status_dashboard}
