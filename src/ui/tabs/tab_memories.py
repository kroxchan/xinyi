"""Tab: tab_memories — extracted from app.py"""
from __future__ import annotations

def render_tab_memories(components=None):
    gr.Markdown(
        "### 记忆库管理\n"
        "查看、搜索、编辑从聊天记录中提取的事实记忆。\n"
        "置信度越高 = 越多次提到、越可信。聊天时只有「可能」和「确定」级别的记忆会被使用。"
    )
    with gr.Row():
        mem_search = gr.Textbox(label="搜索记忆", placeholder="输入关键词，留空显示全部", scale=4)
        mem_search_btn = gr.Button("查询", scale=1)
    mem_table = gr.DataFrame(
        value=query_memories("") if components and components.get("memory_bank") else None,
        headers=["ID", "类型", "内容", "置信度", "提及次数", "状态"],
        interactive=False,
        wrap=True,
        column_widths=["6%", "8%", "46%", "10%", "10%", "8%"],
    )

    gr.Markdown("---\n#### 编辑记忆")
    with gr.Row():
        mem_edit_id = gr.Textbox(label="记忆 ID", placeholder="从表格中查看", scale=1)
        mem_edit_content = gr.Textbox(label="新内容（留空不改）", placeholder="修改记忆内容", scale=3)
        mem_edit_conf = gr.Textbox(label="新置信度（0~1，留空不改）", placeholder="如 0.8", scale=1)
    with gr.Row():
        mem_save_btn = gr.Button("保存修改", variant="secondary", scale=1)
        mem_del_btn = gr.Button("🗑 删除此记忆", variant="stop", scale=1)
    mem_edit_result = gr.HTML()

    gr.Markdown("---\n#### 手动添加记忆")
    with gr.Row():
        mem_add_type = gr.Dropdown(
            label="类型",
            choices=[
                ("事实", "fact"), ("经历", "event"), ("偏好", "preference"),
                ("计划", "plan"), ("人际关系", "relationship"), ("习惯", "habit"),
            ],
            value="fact",
            scale=1,
        )
        mem_add_content = gr.Textbox(label="记忆内容", placeholder="如：我在腾讯工作", scale=4)
        mem_add_btn = gr.Button("添加", variant="primary", scale=1)
    mem_add_result = gr.HTML()

    mem_search_btn.click(fn=query_memories, inputs=mem_search, outputs=mem_table)
    mem_search.submit(fn=query_memories, inputs=mem_search, outputs=mem_table)
    mem_save_btn.click(fn=edit_memory, inputs=[mem_edit_id, mem_edit_content, mem_edit_conf], outputs=[mem_edit_result, mem_table])
    mem_del_btn.click(fn=delete_memory, inputs=mem_edit_id, outputs=[mem_edit_result, mem_table])
    mem_add_btn.click(fn=add_memory_manual, inputs=[mem_add_type, mem_add_content], outputs=[mem_add_result, mem_table])

    # (情感调解Tab已合并入聊天Tab)

    # ================================================================
    # Tab: System Info
    # ================================================================
