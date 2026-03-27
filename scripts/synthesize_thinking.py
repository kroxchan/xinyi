"""Cross-scenario synthesis: aggregate 4 scenario analyses into unified thinking model.

Reads the 4 per-scenario analyses, sends them to LLM for cross-scenario synthesis,
then condenses into prompt-ready instructions.
"""
import json
import os
from pathlib import Path

import yaml
from openai import OpenAI


def _load_api_config():
    cfg_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        api = raw.get("api", {})
        def _env(v):
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                inner = v[2:-1]
                key, _, default = inner.partition(":")
                return os.environ.get(key, default or "")
            return v
        return {k: _env(v) for k, v in api.items() if not isinstance(v, dict)}, {
            k: v for k, v in (api.get("headers") or {}).items()
        }
    return {"api_key": os.environ.get("WECHAT_TWIN_API_KEY", ""), "base_url": None, "model": "gpt-4o"}, {}

SCENARIOS = ["loving", "conflict", "daily", "vulnerable"]
ANALYSES = {}
for s in SCENARIOS:
    path = Path(f"/tmp/thinking_batches/{s}_analysis.txt")
    ANALYSES[s] = path.read_text("utf-8")

LABELS = {
    "loving": "甜蜜/恋爱场景",
    "conflict": "冲突/生气场景",
    "daily": "日常/轻松场景",
    "vulnerable": "脆弱/焦虑场景",
}

SYNTHESIS_PROMPT = """你是认知心理学家。下面是对同一个人在 4 种不同情境下的行为模式分析报告。每份报告都基于 25 段真实微信对话、附有原文证据。

你的任务：
1. **找出跨情境一致的核心认知模式**（在所有场景里都稳定出现的思维方式、反应逻辑、内在信念）
2. **找出情境特异性反应**（只在特定情境出现的独特反应路径）
3. **构建完整的反应逻辑链**：当遇到不同类型的输入（夸奖、批评、冷战、撒娇、求助、被忽视……）时，此人的典型反应路径是什么？用 IF-THEN 格式写清楚
4. **总结核心信念系统**：驱动此人行为的最底层信念是什么？
5. **标注矛盾和张力**：此人的行为模式中有哪些看似矛盾的地方？（如：既想被依赖又怕太黏人）

要求：
- 每条结论必须标注来自哪个场景报告的证据
- 用第二人称"你"
- 不要写表面语言特征（如"说话很短"），只写思维和反应逻辑
- 输出结构清晰，分层级

{analyses}"""

CONDENSE_PROMPT = """你是 AI 系统提示词专家。下面是一份从 100 段真实微信对话中通过 4 种情境分析、跨情境聚合得出的完整认知模型。

请将它**浓缩成可直接放进 AI 系统提示词的指令集**。要求：

1. **核心身份**：用 2-3 句话定义"你是谁、你怎么看世界"
2. **反应路径表**：用 IF→THEN 格式写出 10-15 条最重要的反应路径
   格式："当[触发条件]时 → 你的第一反应是[X]，如果[Y]则切换到[Z]"
3. **情境切换规则**：什么时候从甜蜜切到讲理？什么时候从玩笑切到真话？什么时候从安抚切到攻击？
4. **绝对禁止项**：这个人绝对不会做的事（基于数据证据）
5. **核心信念**：3-5 条驱动所有行为的底层信念

格式要求：
- 每条指令可执行、可检验，不要抽象形容词
- 必须包含"如果对方…你就…"的具体反应指南
- 控制在 1200 字以内
- 不要写"你说话很短""你喜欢用emoji"这类表面特征，那些别的模块会处理
- 用条目式，标清编号

原始认知模型：
{synthesis}"""

_api, _headers = _load_api_config()
client = OpenAI(
    api_key=_api.get("api_key", ""),
    base_url=_api.get("base_url") or None,
    default_headers=_headers or None,
)
_model = _api.get("model", "gpt-4o")

analysis_block = ""
for s in SCENARIOS:
    analysis_block += f"\n\n{'='*60}\n## {LABELS[s]}分析\n{'='*60}\n\n{ANALYSES[s]}"

prompt = SYNTHESIS_PROMPT.format(analyses=analysis_block)
print(f"Step 1: Synthesizing {len(SCENARIOS)} scenarios ({len(prompt)} chars)...")

resp = client.chat.completions.create(
    model=_model,
    messages=[
        {"role": "system", "content": "你是认知心理学家，专精从行为数据中构建认知模型。你的工作是找到跨情境的一致模式，而不是重复各场景的描述。"},
        {"role": "user", "content": prompt},
    ],
    temperature=0.3,
    max_tokens=6000,
)
synthesis = resp.choices[0].message.content or ""
Path("/tmp/thinking_batches/synthesis.txt").write_text(synthesis, encoding="utf-8")
print(f"Step 1 done: {len(synthesis)} chars")

condense_prompt = CONDENSE_PROMPT.format(synthesis=synthesis)
print(f"Step 2: Condensing into prompt instructions ({len(condense_prompt)} chars)...")

resp2 = client.chat.completions.create(
    model=_model,
    messages=[
        {"role": "system", "content": "你是AI提示词工程师。你的任务是把心理学分析转化成可执行的AI行为指令。指令必须具体到'当X时做Y'的程度。"},
        {"role": "user", "content": condense_prompt},
    ],
    temperature=0.3,
    max_tokens=3000,
)
condensed = resp2.choices[0].message.content or ""

out_path = Path(__file__).resolve().parent.parent / "data" / "thinking_model.txt"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(condensed, encoding="utf-8")
print(f"Step 2 done: {len(condensed)} chars -> {out_path}")

synth_path = Path(__file__).resolve().parent.parent / "data" / "thinking_profile.txt"
synth_path.write_text(synthesis, encoding="utf-8")
print(f"Full synthesis also saved to {synth_path}")
