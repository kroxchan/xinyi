"""Data-driven thinking model extraction.

Multi-batch pipeline:
1. Classify conversations by emotional scenario
2. For each scenario, use LLM to extract thinking patterns with evidence
3. Cross-scenario synthesis to find consistent patterns
4. Condense into prompt-ready instructions

The resulting model comes entirely from conversation data analysis,
not from manual prompt engineering.
"""

from __future__ import annotations

import json
import logging
import random
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

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

SYNTHESIS_PROMPT = """你是认知心理学家。下面是对同一个人在 {n_scenarios} 种不同情境下的行为模式分析报告。每份报告都基于真实微信对话、附有原文证据。

你的任务：
1. **找出跨情境一致的核心认知模式**（在所有场景里都稳定出现的思维方式、反应逻辑、内在信念）
2. **找出情境特异性反应**（只在特定情境出现的独特反应路径）
3. **构建完整的反应逻辑链**：当遇到不同类型的输入（夸奖、批评、冷战、撒娇、求助、被忽视……）时，此人的典型反应路径是什么？用 IF-THEN 格式写清楚
4. **总结核心信念系统**：驱动此人行为的最底层信念是什么？
5. **标注矛盾和张力**：此人的行为模式中有哪些看似矛盾的地方？

要求：
- 每条结论必须标注来自哪个场景报告的证据
- 用第二人称"你"
- 不要写表面语言特征（如"说话很短"），只写思维和反应逻辑
- 输出结构清晰，分层级

{analyses}"""

CONDENSE_PROMPT = """你是 AI 系统提示词专家。下面是一份从真实微信对话中通过多情境分析、跨情境聚合得出的完整认知模型。

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
- 用纯文本，禁止使用markdown格式（不要加粗、不要用#标题）
- 用数字编号，简洁直接

原始认知模型：
{synthesis}"""


def _detect_emotion(text: str) -> str:
    """Lightweight keyword-based emotion detection for bucketing."""
    if not isinstance(text, str):
        return "neutral"
    joy_kw = ["哈哈", "哈哈哈", "666", "牛", "太好了", "开心", "好棒", "嘻嘻", "美滋滋"]
    excitement_kw = ["冲", "太棒了", "等不及", "好期待", "兴奋", "燃", "激动", "终于"]
    touched_kw = ["感动", "好暖", "暖心", "泪目", "太感动", "破防了", "戳心"]
    gratitude_kw = ["谢谢", "感谢", "多谢", "辛苦了", "太感谢", "感恩"]
    pride_kw = ["骄傲", "自豪", "厉害了", "太牛了", "真棒", "为你骄傲"]
    sadness_kw = ["难过", "想哭", "心累", "心碎", "伤心", "好难过", "崩溃", "绝望", "呜呜"]
    anger_kw = ["烦", "无语", "服了", "够了", "离谱", "受不了", "搞什么", "神经", "有毛病", "烦死了", "气死", "滚"]
    anxiety_kw = ["怎么办", "担心", "焦虑", "紧张", "急", "害怕", "不安", "慌了", "压力大"]
    disappointment_kw = ["失望", "白期待了", "还以为", "本以为", "算了吧", "没意思", "不过如此"]
    wronged_kw = ["委屈", "凭什么", "冤枉", "不公平", "为什么要这样", "被误解"]
    coquettish_kw = ["宝宝", "人家", "嘤嘤嘤", "哼", "你说嘛", "不嘛", "求求了", "哄哄我"]
    jealousy_kw = ["吃醋", "嫉妒", "你和谁", "不许", "你是不是有别人了", "少跟她聊"]
    heartache_kw = ["心疼", "好心疼", "别太累", "照顾好自己", "看着都疼", "受苦了"]
    longing_kw = ["想你", "好想你", "想见你", "什么时候回来", "快回来", "好久没见", "想死你了"]
    curiosity_kw = ["为什么", "怎么回事", "然后呢", "什么意思", "真的吗", "讲讲", "细说", "好奇"]
    sarcastic_kw = ["呵呵", "是吗", "行吧", "可以可以", "厉害了"]

    t = text.lower()
    scores = {
        "joy": sum(1 for k in joy_kw if k in t),
        "excitement": sum(1 for k in excitement_kw if k in t),
        "touched": sum(1 for k in touched_kw if k in t),
        "gratitude": sum(1 for k in gratitude_kw if k in t),
        "pride": sum(1 for k in pride_kw if k in t),
        "sadness": sum(1 for k in sadness_kw if k in t),
        "anger": sum(1 for k in anger_kw if k in t),
        "anxiety": sum(1 for k in anxiety_kw if k in t),
        "disappointment": sum(1 for k in disappointment_kw if k in t),
        "wronged": sum(1 for k in wronged_kw if k in t),
        "coquettish": sum(1 for k in coquettish_kw if k in t),
        "jealousy": sum(1 for k in jealousy_kw if k in t),
        "heartache": sum(1 for k in heartache_kw if k in t),
        "longing": sum(1 for k in longing_kw if k in t),
        "curiosity": sum(1 for k in curiosity_kw if k in t),
        "sarcastic": sum(1 for k in sarcastic_kw if k in t),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "neutral"


class ThinkingProfiler:
    """Data-driven thinking model extraction from conversations."""

    # 各类 LLM 调用的 timeout（秒），反代慢时可在 config 中覆盖
    _DEFAULT_TIMEOUTS = {
        "analyze_scenario": 120,
        "synthesize": 180,
        "condense": 120,
        "cognitive_profile": 60,
        "emotion_boundaries": 120,
        "emotion_expression": 60,
    }

    def __init__(
        self,
        api_client,
        model: str,
        timeouts: dict | None = None,
        runner=None,
    ) -> None:
        self.client = api_client
        self.model = model
        self._timeouts = {**self._DEFAULT_TIMEOUTS, **(timeouts or {})}
        self._runner = runner  # heartbeat progress updates

    def _llm(
        self,
        call_type: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        """统一 LLM 调用入口，自动应用 timeout 并记录耗时。"""
        timeout = self._timeouts.get(call_type, 120)
        import time as _llm_time
        t0 = _llm_time.time()
        logger.info("[LLM] %s 开始 (timeout=%ds)", call_type, timeout)
        if self._runner:
            self._runner.update("⏳ {} 中…".format(call_type))
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        elapsed = _llm_time.time() - t0
        result = resp.choices[0].message.content or ""
        logger.info("[LLM] %s 完成，耗时 %.1fs，%d 字", call_type, elapsed, len(result))
        return result

    def _classify_conversation(self, text: str) -> str:
        """Classify a conversation into an emotional scenario bucket."""
        my_lines = [l.replace("我: ", "") for l in text.split("\n") if l.startswith("我:")]
        emotions = [_detect_emotion(l) for l in my_lines]
        c = Counter(emotions)
        c.pop("neutral", None)
        if not c:
            other_lines = [l.replace("对方: ", "") for l in text.split("\n") if l.startswith("对方:")]
            other_emos = [_detect_emotion(l) for l in other_lines]
            other_c = Counter(other_emos)
            other_c.pop("neutral", None)
            if other_c:
                return "responding_to_" + other_c.most_common(1)[0][0]
            return "daily"
        return c.most_common(1)[0][0]

    def _bucket_conversations(self, conversations: list[dict]) -> dict[str, list[str]]:
        """Sort conversations into 4 emotional scenario buckets."""
        raw_buckets: dict[str, list[str]] = {}
        for c in conversations:
            text = c.get("text", "")
            if not text or len(text) < 80:
                continue
            if text.count("我:") < 3:
                continue
            cat = self._classify_conversation(text)
            raw_buckets.setdefault(cat, []).append(text)

        buckets = {"loving": [], "conflict": [], "daily": [], "vulnerable": []}
        for cat, texts in raw_buckets.items():
            if cat in (
                "coquettish", "longing", "heartache",
                "responding_to_coquettish", "responding_to_longing",
                "responding_to_heartache",
            ):
                buckets["loving"].extend(texts)
            elif cat in (
                "anger", "jealousy", "sarcastic", "disappointment", "wronged",
                "responding_to_anger", "responding_to_jealousy",
                "responding_to_disappointment", "responding_to_wronged",
            ):
                buckets["conflict"].extend(texts)
            elif cat in (
                "sadness", "anxiety",
                "responding_to_sadness", "responding_to_anxiety",
            ):
                buckets["vulnerable"].extend(texts)
            else:
                buckets["daily"].extend(texts)

        random.seed(42)
        for name in buckets:
            random.shuffle(buckets[name])
            buckets[name] = buckets[name][:25]

        return buckets

    def _analyze_scenario(self, scenario: str, texts: list[str]) -> str:
        """Send one scenario batch to LLM for pattern extraction."""
        conv_block = ""
        for i, t in enumerate(texts, 1):
            conv_block += f"\n=== 对话{i} ===\n{t}\n"

        label = SCENARIO_LABELS.get(scenario, scenario)
        prompt = EXTRACT_PROMPT.format(scenario=label, n=len(texts), conversations=conv_block)

        logger.info("[%s] Analyzing %d conversations...", scenario, len(texts))
        return self._llm(
            "analyze_scenario",
            system_prompt="你是认知心理学家，专精从真实对话数据中提取行为模式和认知结构。你的分析必须严格基于数据证据，不能凭空推测。",
            user_prompt=prompt,
            max_tokens=4000,
        )

    def _synthesize(self, analyses: dict[str, str]) -> str:
        """Cross-scenario synthesis."""
        analysis_block = ""
        for s, text in analyses.items():
            label = SCENARIO_LABELS.get(s, s)
            analysis_block += f"\n\n{'=' * 60}\n## {label}分析\n{'=' * 60}\n\n{text}"

        prompt = SYNTHESIS_PROMPT.format(n_scenarios=len(analyses), analyses=analysis_block)
        logger.info("Synthesizing %d scenario analyses...", len(analyses))
        return self._llm(
            "synthesize",
            system_prompt="你是认知心理学家，专精从行为数据中构建认知模型。你的工作是找到跨情境的一致模式，而不是重复各场景的描述。",
            user_prompt=prompt,
            max_tokens=6000,
        )

    def _condense(self, synthesis: str) -> str:
        """Condense synthesis into prompt-ready instructions."""
        prompt = CONDENSE_PROMPT.format(synthesis=synthesis)
        logger.info("Condensing into prompt instructions...")
        return self._llm(
            "condense",
            system_prompt="你是AI提示词工程师。你的任务是把心理学分析转化成可执行的AI行为指令。指令必须具体到'当X时做Y'的程度。",
            user_prompt=prompt,
            max_tokens=3000,
        )

    def train(
        self,
        conversations: list[dict],
        contact_wxid: str | None = None,
        progress_callback=None,
        runner=None,
    ) -> str:
        """Full training pipeline: bucket → per-scenario analysis → synthesis → condense.

        Args:
            conversations: list of conversation dicts with 'text' and 'contact' keys
            contact_wxid: optional filter to train only on a specific contact
            progress_callback: optional callable(step_name, detail) for UI updates
            runner: optional TrainingRunner for heartbeat progress

        Returns:
            Condensed thinking model text ready for prompt injection.
        """
        _runner = runner or self._runner

        def _progress(step, detail=""):
            if progress_callback:
                progress_callback(step, detail)
            if _runner:
                _runner.update("⚡ {}: {}".format(step, detail))
            logger.info("[ThinkingProfiler] %s: %s", step, detail)

        if contact_wxid:
            conversations = [c for c in conversations if c.get("contact") == contact_wxid]

        _progress("分类对话", f"总计 {len(conversations)} 段对话")
        buckets = self._bucket_conversations(conversations)

        bucket_info = ", ".join(f"{k}:{len(v)}" for k, v in buckets.items())
        _progress("分类完成", bucket_info)

        analyses = {}
        for scenario, texts in buckets.items():
            if len(texts) < 3:
                _progress(f"跳过 {scenario}", f"对话不足 ({len(texts)})")
                continue
            _progress(f"分析 {scenario}", f"{len(texts)} 段对话")
            analyses[scenario] = self._analyze_scenario(scenario, texts)

        if not analyses:
            _progress("失败", "没有足够的对话数据进行分析")
            return ""

        _progress("跨情境聚合", f"综合 {len(analyses)} 个场景")
        synthesis = self._synthesize(analyses)

        _progress("生成指令集", "浓缩为 prompt 指令")
        condensed = self._condense(synthesis)

        _progress("完成", f"思维模型 {len(condensed)} 字")
        return condensed

    # Legacy single-shot method kept for backward compat
    def extract_from_conversations(
        self,
        conversations: list[dict],
        contact_wxid: str | None = None,
        n_samples: int = 20,
    ) -> str:
        """Legacy single-shot extraction. Use train() for data-driven pipeline."""
        return self.train(conversations, contact_wxid)

    # ------------------------------------------------------------------
    # Cognitive profile extraction (research-informed)
    # ------------------------------------------------------------------

    _EMOTION_BOUNDARY_PROMPT = (
        "你是认知心理学家。下面是同一个人（标记为「我」）在多种情境下的真实微信聊天片段。\n"
        "你的任务是从数据中提取这个人的**情绪反应边界**——面对不同类型的刺激，TA实际产生的情绪是什么。\n\n"
        "聊天片段：\n{samples}\n\n"
        "请分析这个人面对以下刺激类型时的真实情绪反应，只输出JSON数组：\n"
        "[\n"
        '  {{"stimulus": "刺激类型描述", "emotion": "实际情绪", "intensity": "typical强度0-1", "evidence": "对话原文证据"}}\n'
        "]\n\n"
        "刺激类型请从数据中归纳，常见的包括但不限于：\n"
        "- 被直接辱骂/挑衅\n"
        "- 被忽视/冷落/不回消息\n"
        "- 被误解/被冤枉\n"
        "- 对方撒娇/示弱\n"
        "- 对方夸奖/认可\n"
        "- 对方开玩笑/调侃\n"
        "- 收到坏消息\n"
        "- 日常闲聊/无事发生\n"
        "- 对方求助/提问\n\n"
        "要求：\n"
        "- emotion 必须是：joy/excitement/touched/gratitude/pride/sadness/anger/anxiety/disappointment/wronged/coquettish/jealousy/heartache/longing/curiosity/neutral 之一\n"
        "- 只写数据里有证据的，没观察到的不要编\n"
        "- intensity 是这个人面对该刺激的典型反应强度\n"
        "- 同一刺激如果有不同反应模式（比如被调侃时有时笑有时生气），写多条\n"
        "- 最多15条，覆盖最重要的情绪触发场景\n"
    )

    _COGNITIVE_PROFILE_PROMPT = (
        "你是认知心理学家。根据下面这个人在多种情境下的真实微信聊天片段，提取TA的**认知风格参数**。\n"
        "这些参数将用于模拟TA收到消息后的内心思考过程。\n\n"
        "聊天片段（「我」是被分析的人）：\n{samples}\n\n"
        "请从以下维度分析，只输出JSON：\n"
        '{{\n'
        '  "emotional_reactivity": "情绪反应性：high/medium/low — 收到消息后情绪波动有多大？是容易激动还是不太有反应？",\n'
        '  "thinking_style": "思考风格：emotional_first/analytical_first/action_first — 是先有情绪再理性分析，还是先分析再产生情绪，还是直接想怎么做？",\n'
        '  "conflict_strategy": "冲突策略：confront/deflect/withdraw/humor — 面对冲突时的第一反应是直面、转移话题、退缩还是用幽默化解？",\n'
        '  "contagion_susceptibility": "情绪易感性：high/medium/low — 对方情绪多大程度会传染给TA？是很容易被带动还是情绪稳定？",\n'
        '  "system2_threshold": "深度思考阈值：low/medium/high — 多复杂的消息才会触发TA的深度思考？low=经常深想，high=大多靠直觉",\n'
        '  "response_tempo": "回复节奏偏好：impulsive/measured/slow — 快速冲动回复、适度斟酌还是慢慢想？",\n'
        '  "evidence": "用1-2个具体对话片段支撑以上判断"\n'
        '}}\n\n'
        "要求：\n"
        "- 每个字段必须从上面给的选项中选择\n"
        "- evidence 必须引用真实对话原文\n"
        "- 不要泛泛而谈，要基于数据中的具体行为模式\n"
    )

    def extract_cognitive_profile(
        self,
        conversations: list[dict],
        progress_callback=None,
        runner=None,
    ) -> dict:
        """Extract cognitive style parameters from conversation data.

        Based on Big Five personality research, CAPS theory (IF-THEN behavioral
        signatures), and appraisal theory. The output tunes how the inner
        thinking stage processes messages.
        """
        _runner = runner or self._runner

        def _progress(step, detail=""):
            if progress_callback:
                progress_callback(step, detail)
            if _runner:
                _runner.update("⚡ {}: {}".format(step, detail))
            logger.info("[CognitiveProfile] %s: %s", step, detail)

        _progress("采样对话", f"总计 {len(conversations)} 段")
        buckets = self._bucket_conversations(conversations)

        samples_block = ""
        total = 0
        for scenario, texts in buckets.items():
            chosen = texts[:8]
            for i, t in enumerate(chosen, 1):
                samples_block += f"\n=== {scenario} 片段{i} ===\n{t}\n"
                total += 1
        if total < 5:
            _progress("数据不足", "需要至少5段有效对话")
            return {}

        _progress("提取认知参数", f"分析 {total} 段对话")
        prompt = self._COGNITIVE_PROFILE_PROMPT.format(samples=samples_block)

        try:
            raw = self._llm(
                "cognitive_profile",
                system_prompt="你是认知心理学家，专精从行为数据中推断个体认知风格。你的判断必须基于对话中的具体行为证据。",
                user_prompt=prompt,
                max_tokens=800,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            profile = json.loads(raw)
            _progress("完成", json.dumps(profile, ensure_ascii=False)[:120])
            return profile
        except Exception:
            logger.warning("Cognitive profile extraction failed", exc_info=True)
            _progress("失败", "LLM 调用异常")
            return {}

    _REL_NORMALIZE = {
        "partner": "partner", "girlfriend": "partner", "boyfriend": "partner",
        "family": "family", "group_family": "family",
        "close_friend": "friend", "friend": "friend",
        "group_close_friend": "friend", "group_friend": "friend",
        "colleague": "colleague", "group_colleague": "colleague",
        "acquaintance": "acquaintance", "service": "other",
        "group_chat": "other", "unknown": "other",
    }

    def extract_emotion_boundaries(
        self,
        conversations: list[dict],
        contact_registry=None,
        progress_callback=None,
        runner=None,
    ) -> dict[str, list[dict]]:
        """Extract emotion boundaries partitioned by relationship type.

        Returns dict like {"partner": [...], "friend": [...], "default": [...]}.
        Only relationship types with enough data get their own boundaries.
        """
        _runner = runner or self._runner

        def _progress(step, detail=""):
            if progress_callback:
                progress_callback(step, detail)
            if _runner:
                _runner.update("⚡ {}: {}".format(step, detail))
            logger.info("[EmotionBoundary] %s: %s", step, detail)

        _progress("按关系分组", f"总计 {len(conversations)} 段")

        rel_groups: dict[str, list[dict]] = {}
        for c in conversations:
            wxid = c.get("contact", "")
            rel_raw = "other"
            if contact_registry and wxid:
                rel_raw = contact_registry.get_relationship(wxid)
            rel_type = self._REL_NORMALIZE.get(rel_raw, "other")
            rel_groups.setdefault(rel_type, []).append(c)

        group_info = ", ".join(f"{k}:{len(v)}" for k, v in rel_groups.items())
        _progress("分组完成", group_info)

        all_boundaries: dict[str, list[dict]] = {}
        min_convs = 20

        for rel_type, convs in rel_groups.items():
            if len(convs) < min_convs:
                _progress(f"跳过 {rel_type}", f"仅 {len(convs)} 段，需要 ≥{min_convs}")
                continue
            result = self._extract_boundaries_for_group(rel_type, convs, _progress)
            if result:
                all_boundaries[rel_type] = result

        if not all_boundaries:
            _progress("回退到全量提取", "各关系类型数据均不足")
            result = self._extract_boundaries_for_group("default", conversations, _progress)
            if result:
                all_boundaries["default"] = result

        total = sum(len(v) for v in all_boundaries.values())
        _progress("完成", f"{len(all_boundaries)} 个关系类型，共 {total} 条边界")
        return all_boundaries

    def _extract_boundaries_for_group(
        self, rel_type: str, conversations: list[dict], _progress,
    ) -> list[dict]:
        """Extract emotion boundaries for one relationship type group."""
        _progress(f"提取 {rel_type}", f"分析 {len(conversations)} 段对话")
        buckets = self._bucket_conversations(conversations)

        samples_block = ""
        total = 0
        for scenario, texts in buckets.items():
            chosen = texts[:8]
            for i, t in enumerate(chosen, 1):
                samples_block += f"\n=== {scenario} 片段{i} ===\n{t}\n"
                total += 1
        if total < 3:
            return []

        rel_label = {"partner": "伴侣", "family": "家人", "friend": "朋友",
                      "colleague": "同事", "acquaintance": "认识的人",
                      "other": "其他人", "default": "所有关系"}.get(rel_type, rel_type)
        prompt = (
            f"注意：以下对话全部来自该用户与「{rel_label}」的聊天。\n"
            f"提取的情绪边界必须体现TA面对{rel_label}时的特定反应模式。\n\n"
            + self._EMOTION_BOUNDARY_PROMPT.format(samples=samples_block)
        )

        try:
            raw = self._llm(
                "emotion_boundaries",
                system_prompt="你是认知心理学家，从行为数据中推断个体情绪反应模式。只基于数据证据判断。",
                user_prompt=prompt,
                max_tokens=1500,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            boundaries = json.loads(raw)
            if not isinstance(boundaries, list):
                return []
            valid = {
                "joy", "excitement", "touched", "gratitude", "pride",
                "sadness", "anger", "anxiety", "disappointment", "wronged",
                "coquettish", "jealousy", "heartache", "longing",
                "curiosity", "neutral",
            }
            boundaries = [b for b in boundaries if isinstance(b, dict) and b.get("emotion") in valid]
            _progress(f"{rel_type} 完成", f"{len(boundaries)} 条")
            return boundaries
        except Exception:
            logger.warning("Emotion boundary extraction failed for %s", rel_type, exc_info=True)
            return []

    _EMOTION_EXPRESSION_PROMPT = (
        "你是认知心理学家。下面是同一个人（标记为「我」）的真实微信聊天片段，这些片段涵盖了不同情绪状态。\n"
        "你的任务是从数据中归纳这个人**在各种情绪下的语言表达方式**。\n\n"
        "聊天片段：\n{samples}\n\n"
        "以下每种情绪都需要分析：joy, excitement, touched, gratitude, pride, sadness, anger, anxiety, disappointment, wronged, coquettish, jealousy, heartache, longing, curiosity, neutral\n\n"
        "分析这个人在以上每种情绪下，实际是怎么说话的。只输出JSON：\n"
        '{{\n'
        '  "anger": {{"style": "一句话描述表达方式", "typical_words": ["从数据中提取的该情绪下常用词/句式"], "example": "数据中的原话"}},\n'
        '  "coquettish": {{"style": "...", "typical_words": [...], "example": "..."}},\n'
        '  "longing": {{"style": "...", "typical_words": [...], "example": "..."}},\n'
        '  "joy": {{"style": "...", "typical_words": [...], "example": "..."}},\n'
        '  "sadness": {{"style": "...", "typical_words": [...], "example": "..."}},\n'
        '  "anxiety": {{"style": "...", "typical_words": [...], "example": "..."}}\n'
        '}}\n\n'
        "要求：\n"
        "- 只写数据里观察到的情绪，没观察到的不写\n"
        "- typical_words 必须是数据中实际出现的词/句式，不要编造\n"
        "- style 描述这个人表达该情绪时的语言特征（骂人、冷漠、撒娇、幽默等）\n"
        "- example 必须是数据原文\n"
        "- 重点关注：这个人生气时骂不骂人、怎么骂、撒娇时用什么语气词\n"
    )

    def extract_emotion_expression_style(
        self,
        conversations: list[dict],
        progress_callback=None,
        runner=None,
    ) -> dict:
        """Extract HOW the user expresses each emotion from conversation data.

        Returns dict like:
        {"anger": {"style": "...", "typical_words": [...], "example": "..."}, ...}
        """
        _runner = runner or self._runner

        def _progress(step, detail=""):
            if progress_callback:
                progress_callback(step, detail)
            if _runner:
                _runner.update("⚡ {}: {}".format(step, detail))
            logger.info("[EmotionExpression] %s: %s", step, detail)

        _progress("采样对话", f"总计 {len(conversations)} 段")
        buckets = self._bucket_conversations(conversations)

        samples_block = ""
        total = 0
        for scenario, texts in buckets.items():
            chosen = texts[:10]
            for i, t in enumerate(chosen, 1):
                samples_block += f"\n=== {scenario} 片段{i} ===\n{t}\n"
                total += 1
        if total < 5:
            _progress("数据不足", "需要至少5段")
            return {}

        _progress("提取情绪表达风格", f"分析 {total} 段对话")
        prompt = self._EMOTION_EXPRESSION_PROMPT.format(samples=samples_block)

        try:
            raw = self._llm(
                "emotion_expression",
                system_prompt="你是认知心理学家，从对话数据中分析个体的情绪表达方式。只基于数据证据判断，不要编造。",
                user_prompt=prompt,
                max_tokens=1200,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            if not isinstance(result, dict):
                return {}
            _progress("完成", f"{len(result)} 种情绪表达方式")
            return result
        except Exception:
            logger.warning("Emotion expression extraction failed", exc_info=True)
            _progress("失败", "LLM 调用异常")
            return {}

    @staticmethod
    def save_emotion_expression(data: dict, filepath: str = "data/emotion_expression.json") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Emotion expression style saved to %s", filepath)

    @staticmethod
    def load_emotion_expression(filepath: str = "data/emotion_expression.json") -> dict:
        path = Path(filepath)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def save_emotion_boundaries(boundaries, filepath: str = "data/emotion_boundaries.json") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(boundaries, ensure_ascii=False, indent=2), encoding="utf-8")
        count = sum(len(v) for v in boundaries.values()) if isinstance(boundaries, dict) else len(boundaries)
        logger.info("Emotion boundaries saved to %s (%d entries)", filepath, count)

    @staticmethod
    def load_emotion_boundaries(filepath: str = "data/emotion_boundaries.json"):
        """Load emotion boundaries. Returns dict (new format) or list (legacy)."""
        path = Path(filepath)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return data  # legacy format, handled by consumers
            return {}
        except Exception:
            return {}

    @staticmethod
    def save_cognitive_profile(profile: dict, filepath: str = "data/cognitive_profile.json") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Cognitive profile saved to %s", filepath)

    @staticmethod
    def load_cognitive_profile(filepath: str = "data/cognitive_profile.json") -> dict:
        path = Path(filepath)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def save(profile: str, filepath: str = "data/thinking_model.txt") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(profile, encoding="utf-8")
        logger.info("Thinking model saved to %s (%d chars)", filepath, len(profile))

    @staticmethod
    def save_full(synthesis: str, filepath: str = "data/thinking_profile.txt") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(synthesis, encoding="utf-8")
        logger.info("Full synthesis saved to %s", filepath)

    @staticmethod
    def load(filepath: str = "data/thinking_model.txt") -> str:
        path = Path(filepath)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
