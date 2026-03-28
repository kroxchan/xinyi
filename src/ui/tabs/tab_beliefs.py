"""Tab: tab_beliefs — extracted from app.py"""
from __future__ import annotations

def render_tab_beliefs(components=None):
    with gr.Row():
        belief_search = gr.Textbox(
            label="按主题搜索",
            placeholder="输入关键词搜索信念，留空显示全部",
            scale=4,
        )
        belief_btn = gr.Button("查询", scale=1)
    belief_table = gr.DataFrame(
        headers=["主题", "立场", "前提条件", "置信度", "来源"],
        interactive=False,
        wrap=True,
    )
    belief_btn.click(fn=query_beliefs, inputs=belief_search, outputs=belief_table)
    belief_search.submit(fn=query_beliefs, inputs=belief_search, outputs=belief_table)

    # ================================================================
    # Tab: Memory Bank
    # ================================================================
