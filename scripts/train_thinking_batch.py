"""Per-scenario thinking pattern extraction.

Usage: python scripts/train_thinking_batch.py <batch_name>
batch_name: loving | conflict | daily | vulnerable

Reads /tmp/thinking_batches/<batch_name>.json
Outputs /tmp/thinking_batches/<batch_name>_analysis.txt
"""
import json
import sys
from pathlib import Path
from openai import OpenAI

BATCH_NAME = sys.argv[1]
INPUT = Path(f"/tmp/thinking_batches/{BATCH_NAME}.json")
OUTPUT = Path(f"/tmp/thinking_batches/{BATCH_NAME}_analysis.txt")

SCENARIO_LABELS = {
    "loving": "甜蜜、恋爱、撒娇、表达爱意",
    "conflict": "冲突、生气、冷战、讽刺",
    "daily": "日常闲聊、开心、轻松话题",
    "vulnerable": "难过、焦虑、脆弱、压力",
}

EXTRACT_PROMPT = """你是一个认知心理学家。下面是同一个人（标记为「我」）在**{scenario}**情境下的 {n} 段真实微信聊天记录。

你的任务不是描述这个人"说了什么"，而是从数据中**归纳出这个人在这类情境下的认知模式和反应逻辑**。

请从以下维度严格基于对话数据分析（每条必须有具体对话证据）：

1. **触发-反应链**：
   - 当对方做/说X时，此人的第一反应是什么？第二反应呢？
   - 列出至少 5 个你在数据中观察到的 [对方行为] → [此人反应] 模式
   - 用引号引用对话原文作为证据

2. **思考策略**：
   - 这个人在这类情境下用什么策略？（转移话题？直面问题？自嘲化解？装不在乎？）
   - 什么时候切换策略？切换的条件是什么？

3. **情绪处理路径**：
   - 情绪是怎么升级或降级的？有什么规律？
   - 这个人是先表达情绪还是先压住？

4. **独特行为模式**（只属于这个人的，不是泛泛的描述）：
   - 哪些反应是你在其他人身上很少见到的？
   - 有什么口头禅或特定句式总是在这类情境出现？

5. **底层逻辑推断**：
   - 基于以上数据，推断这个人在这类情境下的**核心诉求**是什么？
   - 推断驱动这些行为的**内在信念**是什么？

用第二人称"你"描述。每条结论必须附上对话原文证据。直接输出分析文本。

对话记录：
{conversations}"""

client = OpenAI(
    api_key="REDACTED",
    base_url="REDACTED_URL",
    default_headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) OpenClaw/2026.2.14",
        "Accept": "application/json",
    },
)

texts = json.loads(INPUT.read_text("utf-8"))
conv_block = ""
for i, t in enumerate(texts, 1):
    conv_block += f"\n=== 对话{i} ===\n{t}\n"

scenario_label = SCENARIO_LABELS.get(BATCH_NAME, BATCH_NAME)
prompt = EXTRACT_PROMPT.format(
    scenario=scenario_label, n=len(texts), conversations=conv_block
)

print(f"[{BATCH_NAME}] Sending {len(texts)} conversations to LLM...")
resp = client.chat.completions.create(
    model="gpt-5.4",
    messages=[
        {"role": "system", "content": "你是认知心理学家，专精从真实对话数据中提取行为模式和认知结构。你的分析必须严格基于数据证据，不能凭空推测。"},
        {"role": "user", "content": prompt},
    ],
    temperature=0.3,
    max_tokens=4000,
)
analysis = resp.choices[0].message.content or ""
OUTPUT.write_text(analysis, encoding="utf-8")
print(f"[{BATCH_NAME}] Done. Analysis: {len(analysis)} chars -> {OUTPUT}")
