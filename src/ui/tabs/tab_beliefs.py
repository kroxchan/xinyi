"""Tab: tab_beliefs — extracted from app.py"""
from __future__ import annotations

import gradio as gr


def _lazy(name: str):
    import src.app as _m
    return getattr(_m, name)


def render_tab_beliefs(components=None, demo=None):
    query_beliefs = _lazy("query_beliefs")
    refresh_belief_editor = _lazy("refresh_belief_editor")
    load_belief_editor = _lazy("load_belief_editor")
    save_belief_editor = _lazy("save_belief_editor")
    delete_belief_editor = _lazy("delete_belief_editor")
    with gr.Row():
        belief_search = gr.Textbox(
            label="按主题搜索",
            placeholder="输入关键词搜索信念，留空显示全部",
            scale=4,
        )
        belief_btn = gr.Button("查询", scale=1)
    belief_table = gr.DataFrame(
        headers=["ID", "主题", "立场", "前提条件", "置信度", "来源"],
        interactive=False,
        wrap=True,
    )
    belief_btn.click(fn=query_beliefs, inputs=belief_search, outputs=belief_table)
    belief_search.submit(fn=query_beliefs, inputs=belief_search, outputs=belief_table)
    gr.Markdown("---\n#### 手动修正信念")
    with gr.Group():
        belief_select = gr.Dropdown(
            label="选择要编辑的信念",
            choices=[],
            value=None,
            allow_custom_value=False,
        )
        with gr.Row():
            belief_edit_topic = gr.Textbox(label="主题")
            belief_edit_confidence = gr.Textbox(label="置信度", placeholder="0.0 - 1.0")
        belief_edit_stance = gr.Textbox(label="立场", lines=3)
        belief_edit_condition = gr.Textbox(label="前提条件", lines=2)
        belief_edit_source = gr.Textbox(label="来源", placeholder="manual_edit")
        belief_edit_status = gr.Markdown(value="*先搜索或点击查询，再选择一条信念进行编辑*")
        with gr.Row():
            belief_refresh_editor_btn = gr.Button("刷新可编辑列表", scale=1)
            belief_save_btn = gr.Button("保存修改", variant="primary", scale=1)
            belief_delete_btn = gr.Button("删除信念", variant="stop", scale=1)
        belief_btn.click(
            fn=refresh_belief_editor,
            inputs=belief_search,
            outputs=[
                belief_select,
                belief_edit_topic,
                belief_edit_stance,
                belief_edit_condition,
                belief_edit_confidence,
                belief_edit_source,
                belief_edit_status,
            ],
        )
        belief_search.submit(
            fn=refresh_belief_editor,
            inputs=belief_search,
            outputs=[
                belief_select,
                belief_edit_topic,
                belief_edit_stance,
                belief_edit_condition,
                belief_edit_confidence,
                belief_edit_source,
                belief_edit_status,
            ],
        )
        belief_refresh_editor_btn.click(
            fn=refresh_belief_editor,
            inputs=belief_search,
            outputs=[
                belief_select,
                belief_edit_topic,
                belief_edit_stance,
                belief_edit_condition,
                belief_edit_confidence,
                belief_edit_source,
                belief_edit_status,
            ],
        )
        belief_select.change(
            fn=load_belief_editor,
            inputs=belief_select,
            outputs=[
                belief_edit_topic,
                belief_edit_stance,
                belief_edit_condition,
                belief_edit_confidence,
                belief_edit_source,
                belief_edit_status,
            ],
        )
        belief_save_btn.click(
            fn=save_belief_editor,
            inputs=[
                belief_search,
                belief_select,
                belief_edit_topic,
                belief_edit_stance,
                belief_edit_condition,
                belief_edit_confidence,
                belief_edit_source,
            ],
            outputs=[belief_edit_status, belief_table, belief_select],
        )
        belief_delete_btn.click(
            fn=delete_belief_editor,
            inputs=[belief_search, belief_select],
            outputs=[
                belief_edit_status,
                belief_table,
                belief_select,
                belief_edit_topic,
                belief_edit_stance,
                belief_edit_condition,
                belief_edit_confidence,
                belief_edit_source,
            ],
        )
        if demo is not None:
            demo.load(
                fn=refresh_belief_editor,
                inputs=belief_search,
                outputs=[
                    belief_select,
                    belief_edit_topic,
                    belief_edit_stance,
                    belief_edit_condition,
                    belief_edit_confidence,
                    belief_edit_source,
                    belief_edit_status,
                ],
            )
