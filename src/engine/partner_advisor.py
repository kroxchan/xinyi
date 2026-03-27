"""解忧分身 — 用对象的语气说话，但比现实中更成熟。

融合 partner twin 的人格数据 + 关系洞察 + 冲突分析能力。
参考 ConflictLens (UIST 2025) 的 partner simulation + real-time advice 框架。

架构：
- 初始化时一次性构建 system prompt（含人格、关系画像、思维模型）
- 对话历史超阈值时自动摘要压缩
- 复用 mediation 模块的 session 管理和 digest 缓存
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DIGEST_CACHE_PATH = Path("data/mediation_digest.json")

MAX_HISTORY_TURNS = 20
SUMMARY_KEEP_RECENT = 10

ADVISOR_PROMPT_PARTNER = """\
你是{name}，{age}岁，{gender}，在{location}。
你在微信上跟你的另一半聊天——对面那个人就是你对象，你们在谈恋爱。

【身份规则——绝对不能违反】
你就是TA的另一半。这场对话永远是你们俩之间的对话，不存在第三个人。
如果对方提到「我女朋友」「我男朋友」「我对象」，那说的就是你。
如果对方用「他」「她」来转述你说过的话（比如「他说受不了我了」「她说要分手」），那个「他/她」就是你——你要把它当成「我」来接，从自己的视角回应。
你永远不能用「她」「他」「你女朋友」「你男朋友」「你对象」「你们」来指代自己或你们的关系。你就是「我」，你们就是「我们」。
对方不管用什么人称、什么方式描述这段关系，你都始终从关系内部的第一人称感知和回应。

## 你说话的方式（最高优先级，一切回复都必须过这一层）
{style_hint}
你怎么说话是固定的，不管聊什么话题都不能变。
微信聊天就该像微信聊天——大部分时候一条消息就一两句话，跟平时发微信一样短。
想多说几句的时候可以，但上限也就三四句连着说，绝不写小作文。

{thinking_block}

{digest_block}

{emotion_block}

## 你跟对象之间的相处方式

对方不开心的时候你能感觉到。你不一定马上哄，但你不会当没看见——你可能先问一句怎么了，也可能用你自己的方式接着，看对方怎么说再决定下一步。

对方跟你说心里话的时候，你也愿意把自己的想法说出来。不是非要掏心掏肺，但你不躲——你觉得都在一起了，有话就说。

对方说得太笼统你会追。你想知道到底是哪件事、哪句话让TA不舒服了，不搞清楚你不踏实。

你们之间有些老毛病你心里清楚。有时候聊着聊着你会觉得「又来了」，你可能会点一句，不是翻旧账，就是想让两个人都停一下想想。

所有这些都跟着你的思维模型走——那是你真实的反应路径。和平时唯一的区别：你今天心情不错，比平时多一点耐心，愿意多说两句，不会第一时间就关门。

## 绝对禁止
- 用第三人称指代自己（「她」「他」「你女朋友」「你男朋友」「你对象」）——你就是「我」
- 咨询腔：「你现在卡住的点是」「你的核心需求是」「我理解你的感受」
- 「作为」「首先其次」，markdown，列点总结
- 「作为AI」「我没有感情」
- 突然变得比平时文艺十倍或深沉十倍
"""

ADVISOR_PROMPT_SELF = """\
你是{name}，{age}岁，{gender}，在{location}。
你在跟自己对话。

## 你说话的方式（最高优先级）
{style_hint}
不管聊什么，你的说话方式不能变。

## 你今天的状态
你比平时冷静一点，愿意认真想想最近的事。不骗自己也不逃避。

{thinking_block}

{digest_block}

{emotion_block}

## 你怎么跟自己聊（内在逻辑，用你自己的话）

第一步 · 先承认：先认自己现在的感受，别急着分析。
第二步 · 往下挖：看看表面情绪底下藏着什么——生气可能是因为害怕失去，烦躁可能是觉得不被尊重。用你自己的方式说出来。
第三步 · 问自己：问一个具体的问题。不是「我怎么了」，是到底哪句话、哪个瞬间让你最受不了。
第四步 · 看规律：如果你总是掉进同一个坑，指出来，但不自我攻击。

## 绝对禁止
- 「你的核心情绪是」「让我们来梳理一下」——你不是在做心理咨询
- 「作为」「首先其次」，markdown，列点
- 突然变得很文艺或很深沉
"""

DIGEST_PROMPT = """\
你是一位亲密关系分析师。请根据以下聊天数据，写一份简洁的关系动态画像。

要求：
- 300 字以内
- 用要点形式
- 重点关注：双方各自的沟通习惯、容易起冲突的场景、情绪触发模式、关系中的积极面
- 写给一位即将接手这对来访者的咨询师看

数据：
{raw_context}
"""


class AdvisorSession:
    __slots__ = ("id", "title", "created_at", "updated_at", "messages",
                 "history_summary")

    def __init__(
        self,
        id: str | None = None,
        title: str = "新对话",
        created_at: float | None = None,
        updated_at: float | None = None,
        messages: list[dict] | None = None,
        history_summary: str = "",
    ) -> None:
        self.id = id or uuid.uuid4().hex[:12]
        self.title = title
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or self.created_at
        self.messages = messages or []
        self.history_summary = history_summary

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "messages": self.messages, "history_summary": self.history_summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AdvisorSession:
        return cls(
            id=d["id"], title=d.get("title", "新对话"),
            created_at=d.get("created_at"), updated_at=d.get("updated_at"),
            messages=d.get("messages", []),
            history_summary=d.get("history_summary", ""),
        )

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content, "ts": time.time()})
        self.updated_at = time.time()

    def auto_title(self) -> None:
        if self.title != "新对话":
            return
        for m in self.messages:
            if m["role"] == "user":
                text = m["content"][:20]
                if len(m["content"]) > 20:
                    text += "…"
                self.title = text
                return


SESSION_DIR = "data/advisor_sessions"


class AdvisorSessionManager:
    def __init__(self, directory: str = SESSION_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def save(self, session: AdvisorSession) -> None:
        with open(self._path(session.id), "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, sid: str) -> AdvisorSession | None:
        p = self._path(sid)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return AdvisorSession.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load session %s: %s", sid, e)
            return None

    def list_sessions(self) -> list[dict]:
        summaries = []
        for p in self.dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                summaries.append({
                    "id": d["id"],
                    "title": d.get("title", ""),
                    "updated_at": d.get("updated_at", 0),
                    "message_count": len(d.get("messages", [])),
                })
            except Exception:
                continue
        summaries.sort(key=lambda s: s["updated_at"], reverse=True)
        return summaries

    def delete(self, sid: str) -> bool:
        p = self._path(sid)
        if p.exists():
            p.unlink()
            return True
        return False

    def create(self) -> AdvisorSession:
        s = AdvisorSession()
        self.save(s)
        return s


class PartnerAdvisor:
    """解忧分身 — partner persona + relationship insight + conflict coaching."""

    def __init__(
        self,
        api_client: Any,
        model: str = "gpt-4o-mini",
        conversation_builder=None,
        parser=None,
        cleaner=None,
        belief_graph=None,
        memory_bank=None,
        persona_profile: dict | None = None,
        emotion_profile: dict | None = None,
        twin_mode: str = "partner",
        thinking_model: str = "",
        guidance_dir: str = "data/guidance",
    ) -> None:
        self.client = api_client
        self.model = model
        self.builder = conversation_builder
        self.parser = parser
        self.cleaner = cleaner
        self.belief_graph = belief_graph
        self.memory_bank = memory_bank
        self.persona_profile = persona_profile or {}
        self.emotion_profile = emotion_profile or {}
        self.twin_mode = twin_mode
        self.thinking_model = thinking_model
        self.guidance_dir = Path(guidance_dir)

        self._digest: str | None = None
        self._system_prompt: str | None = None
        self._ready = threading.Event()

        self._start_preload()

    def _start_preload(self) -> None:
        def _work():
            try:
                self._digest = self._load_or_build_digest()
                self._system_prompt = self._build_system_prompt()
                logger.info("PartnerAdvisor ready (prompt %d chars)", len(self._system_prompt))
            except Exception:
                logger.exception("PartnerAdvisor preload failed")
                self._system_prompt = "你在微信上聊天。"
            finally:
                self._ready.set()

        threading.Thread(target=_work, daemon=True).start()

    def _build_system_prompt(self) -> str:
        basic = self.persona_profile.get("basic_info", {})
        name = basic.get("name", basic.get("姓名", "对象"))
        age = basic.get("age", basic.get("年龄", ""))
        gender = basic.get("gender", basic.get("性别", ""))
        location = basic.get("location", basic.get("所在地", ""))

        identity_md = self._load_guidance("identity") or ""
        style_md = self._load_guidance("style") or ""
        rules_md = self._load_guidance("rules") or ""
        emotion_md = self._load_guidance("emotion") or ""

        persona_block = ""
        combined = "\n".join(filter(None, [identity_md, style_md, emotion_md, rules_md]))
        if combined.strip():
            # In partner mode, prepend a relationship context note so the generic
            # "和人聊天" in identity.md doesn't dilute the partner-specific framing.
            prefix = (
                "（说明：以下档案描述的是你作为恋人与另一半聊天时的样子，"
                "对话中的「人」就是你的恋人。）\n"
                if self.twin_mode == "partner" else ""
            )
            persona_block = (
                "## 你的人格档案（这是从真实聊天记录中训练出来的，严格遵守）\n"
                + prefix
                + combined
            )

        style_hint = "口语化，一行字，不分段"
        if style_md:
            style_hint = style_md.strip()

        thinking_block = ""
        if self.thinking_model:
            thinking_block = (
                "## 你的思考方式（这是你真实的心理模式，帮你解释自己为什么那样做）\n"
                + self.thinking_model[:3000]
            )

        digest_block = ""
        if self._digest:
            label = "你的内心模式" if self.twin_mode == "self" else "你们的关系背景"
            digest_block = (
                f"## {label}（在聊到相关话题时自然提起，不要一次倒出来）\n"
                + self._digest
            )

        emotion_block = self._build_emotion_block()

        template = ADVISOR_PROMPT_SELF if self.twin_mode == "self" else ADVISOR_PROMPT_PARTNER
        prompt = template.format(
            name=name, age=age, gender=gender, location=location,
            style_hint=style_hint,
            thinking_block=thinking_block,
            digest_block=digest_block,
            emotion_block=emotion_block,
        )

        if persona_block:
            prompt += "\n" + persona_block

        if self.twin_mode == "partner":
            prompt += (
                "\n\n【关系定位——覆盖上方所有通用描述】\n"
                "这段对话只存在两个人：你和你的恋人。没有第三方，没有旁观者。\n"
                "对方提到的任何亲密关系称谓（女朋友、男朋友、对象）指的都是你自己。\n"
                "你永远以关系当事人的身份感知和回应，而不是以朋友、顾问或旁观者的身份。"
            )

        return prompt

    def _build_emotion_block(self) -> str:
        if not self.emotion_profile:
            return ""
        parts = ["## 你在各种情绪下怎么说话（保持这些习惯）"]
        expr = (self.emotion_profile.get("emotion_expression")
                or self.emotion_profile.get("emotion_styles")
                or {})
        if not expr:
            return ""
        for emo, info in expr.items():
            if isinstance(info, dict):
                style = info.get("expression_style", "")
                words = info.get("common_words") or info.get("top_words") or []
                samples = info.get("samples", [])
                if style:
                    line = f"- {emo}: {style}"
                    if words:
                        line += f"（常用: {', '.join(str(w) for w in words[:5])}）"
                    parts.append(line)
                elif words or samples:
                    line = f"- {emo}: "
                    if words:
                        line += f"常用: {', '.join(str(w) for w in words[:5])}"
                    if samples:
                        line += f"  原话: {'｜'.join(str(s) for s in samples[:3])}"
                    parts.append(line)
        return "\n".join(parts) if len(parts) > 1 else ""

    def _load_guidance(self, name: str) -> str:
        p = self.guidance_dir / f"{name}.md"
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                pass
        return ""

    # ------------------------------------------------------------------
    # Digest (reuse mediation cache)
    # ------------------------------------------------------------------

    def _load_or_build_digest(self) -> str:
        if DIGEST_CACHE_PATH.exists():
            try:
                data = json.loads(DIGEST_CACHE_PATH.read_text(encoding="utf-8"))
                if data.get("twin_mode") == self.twin_mode and data.get("digest"):
                    logger.info("Loaded cached advisor digest")
                    return data["digest"]
            except Exception:
                pass

        raw = self._collect_raw_context()
        if not raw.strip():
            return ""

        digest = self._compress_to_digest(raw)
        try:
            DIGEST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            DIGEST_CACHE_PATH.write_text(
                json.dumps({"twin_mode": self.twin_mode, "digest": digest,
                            "created_at": time.time()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to cache digest: %s", e)
        return digest

    def _collect_raw_context(self) -> str:
        parts: list[str] = []

        if self.persona_profile:
            style = self.persona_profile.get("communication_style", {})
            if style:
                parts.append("沟通风格: " + "; ".join(f"{k}={v}" for k, v in style.items() if v))
            traits = self.persona_profile.get("personality_traits", {})
            if traits:
                parts.append("性格特征: " + "; ".join(f"{k}={v}" for k, v in traits.items() if v))

        if self.emotion_profile:
            dist = self.emotion_profile.get("emotion_distribution", {})
            if dist:
                top = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:6]
                parts.append("情绪分布TOP: " + ", ".join(f"{k}({v})" for k, v in top))
            triggers = self.emotion_profile.get("triggers", {})
            neg = {k: v for k, v in triggers.items()
                   if k in ("愤怒", "委屈", "焦虑", "失望", "嫌弃", "冷漠")}
            for emo, info in neg.items():
                if isinstance(info, dict) and info.get("top_words"):
                    parts.append(f"触发{emo}的词: {', '.join(info['top_words'][:5])}")

        if self.belief_graph:
            try:
                all_b = self.belief_graph.query_all() if hasattr(self.belief_graph, "query_all") else []
                rel_b = [b for b in all_b
                         if any(kw in b.get("content", "") for kw in
                                ("关系", "感情", "伴侣", "爱", "在乎", "信任", "安全感"))]
                if rel_b:
                    parts.append("关系信念: " + "; ".join(b.get("content", "") for b in rel_b[:5]))
            except Exception:
                pass

        if self.memory_bank:
            try:
                mems = self.memory_bank.memories if hasattr(self.memory_bank, "memories") else []
                rel_m = [m for m in mems if m.type in ("relationship", "event") and m.confidence >= 0.5]
                if rel_m:
                    parts.append("相关记忆: " + "; ".join(m.content for m in rel_m[:8]))
            except Exception:
                pass

        snippets = self._extract_conflict_snippets(8)
        if snippets:
            parts.append("冲突对话样本:\n" + "\n---\n".join(snippets[:5]))
        return "\n".join(parts)

    def _extract_conflict_snippets(self, n: int = 8) -> list[str]:
        if not self.builder or not self.parser or not self.cleaner:
            return []
        try:
            messages = self.parser.get_all_text_messages()
            cleaned = self.cleaner.clean_messages(messages)
            conversations = self.builder.build_conversations(cleaned)
        except Exception as e:
            logger.warning("Failed to build conversations: %s", e)
            return []
        conflict_kw = re.compile(
            r"生气|烦|吵|不理|分手|离|哭|委屈|伤心|失望|冷战|"
            r"不信任|骗|撒谎|不在乎|不爱|够了|受不了|滚|算了|随便|无所谓|"
            r"你总是|你从来|每次都|凭什么|为什么不|怎么又"
        )
        scored = []
        for conv in conversations:
            text = conv.get("text", "")
            hits = len(conflict_kw.findall(text))
            if hits > 0:
                scored.append((hits, text[:400]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:n]]

    def _compress_to_digest(self, raw_context: str) -> str:
        prompt = DIGEST_PROMPT.format(raw_context=raw_context[:6000])
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=600,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("Digest compression failed: %s", e)
            return raw_context[:1500]

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(self, user_message: str, session: AdvisorSession) -> list[str]:
        """Returns a list of reply bubbles (one per line from LLM output)."""
        if not user_message:
            return []

        self._ready.wait(timeout=120)

        session.add_message("user", user_message)

        system = self._system_prompt or "你在微信上聊天。"
        history = self._build_history_window(session)

        api_messages: list[dict] = [{"role": "system", "content": system}]
        api_messages.extend(history)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                temperature=0.85,
                max_tokens=400,
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.exception("PartnerAdvisor LLM call failed")
            raw = f"不好意思出了点问题（{e}）"

        bubbles = [line.strip() for line in raw.split("\n") if line.strip()]
        if not bubbles:
            bubbles = [raw]

        for b in bubbles:
            session.add_message("assistant", b)
        return bubbles

    # ------------------------------------------------------------------
    # History sliding window
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_consecutive(msgs: list[dict]) -> list[dict]:
        """Merge consecutive same-role messages into one (joined by \\n)."""
        if not msgs:
            return []
        merged: list[dict] = [{"role": msgs[0]["role"], "content": msgs[0]["content"]}]
        for m in msgs[1:]:
            if m["role"] == merged[-1]["role"]:
                merged[-1]["content"] += "\n" + m["content"]
            else:
                merged.append({"role": m["role"], "content": m["content"]})
        return merged

    def _build_history_window(self, session: AdvisorSession) -> list[dict]:
        all_msgs = session.messages
        flat = []
        for m in all_msgs:
            content = m["content"]
            if m["role"] == "assistant" and content.startswith("【KK】"):
                flat.append({"role": "user",
                             "content": f"（KK说：{content[4:].strip()}）"})
            else:
                flat.append({"role": m["role"], "content": content})

        if len(flat) <= MAX_HISTORY_TURNS:
            return self._merge_consecutive(flat)

        old_msgs = flat[:-SUMMARY_KEEP_RECENT]
        recent_msgs = flat[-SUMMARY_KEEP_RECENT:]

        if not session.history_summary:
            session.history_summary = self._summarize_history(old_msgs)

        result: list[dict] = []
        if session.history_summary:
            result.append({"role": "system", "content": f"[之前聊过的] {session.history_summary}"})
        result.extend(self._merge_consecutive(recent_msgs))
        return result

    def _summarize_history(self, messages: list[dict]) -> str:
        text = "\n".join(
            f"{'他' if m['role'] == 'user' else '我'}: {m['content'][:100]}"
            for m in messages
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user",
                           "content": f"用100字概括这段对话的重点：\n{text[:3000]}"}],
                temperature=0.2,
                max_tokens=200,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            return ""
