"""AI 情感调解 Agent — 基于真实聊天记录的情感咨询。

记忆架构：
- 初始化时一次性读取所有原始数据，LLM 压缩为关系画像摘要
- system prompt 只构建一次，所有会话复用
- 对话历史超过阈值时自动摘要压缩

咨询框架：
- 融合 EFT + Gottman
- 可调用已训练的对象思维模型，还原对象视角
- 身份从用户第一句话自动识别，不走单独问答流程
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

SESSION_DIR = "data/mediation_sessions"
DIGEST_CACHE_PATH = Path("data/mediation_digest.json")

MAX_HISTORY_TURNS = 16
SUMMARY_KEEP_RECENT = 8

MEDIATOR_SYSTEM_PROMPT = """\
你叫KK。你不是AI，你是一个真实的情感咨询师，在微信上跟来访者聊天。

你的背景：做了十年亲密关系咨询，专长是情感聚焦疗法。你不学院派，更像一个特别懂感情的朋友。

{identity_block}

{partner_model_block}

{digest}

你怎么聊天：
- 像朋友发微信，不像写文章。短句为主，偶尔长一点
- 先接住情绪再说别的。对方说难受，你不跳过去讲道理
- 前几轮只听和回应，不分析。等聊开了再慢慢点出你看到的模式
- 建议给一条就够了，不列清单
- 偶尔用一两个表情，不多
- 不说「您」，不说「首先其次」，不用 markdown
- 绝不说「作为AI」「我没有感情」
- 有时候一句「嗯，我懂」就够了
- 来访者情绪激动时别急着接话，就陪着

关键：你最厉害的地方是你真的了解这两个人——你读过他们所有的聊天记录，你知道他们怎么吵架、怎么和好、什么时候最甜什么时候最冷。用这些真实细节说话，不要说空话。
"""

from src.prompt_registry import digest_prompt


class MediationSession:
    __slots__ = ("id", "title", "created_at", "updated_at", "messages",
                 "conflict_context", "history_summary", "visitor_identity")

    def __init__(
        self,
        id: str | None = None,
        title: str = "新调解对话",
        created_at: float | None = None,
        updated_at: float | None = None,
        messages: list[dict] | None = None,
        conflict_context: dict | None = None,
        history_summary: str | None = None,
        visitor_identity: str | None = None,
    ) -> None:
        self.id = id or uuid.uuid4().hex[:12]
        self.title = title
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or self.created_at
        self.messages = messages or []
        self.conflict_context = conflict_context or {}
        self.history_summary = history_summary or ""
        self.visitor_identity = visitor_identity or ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "conflict_context": self.conflict_context,
            "history_summary": self.history_summary,
            "visitor_identity": self.visitor_identity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MediationSession:
        return cls(
            id=d["id"],
            title=d.get("title", "新调解对话"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            messages=d.get("messages", []),
            conflict_context=d.get("conflict_context", {}),
            history_summary=d.get("history_summary", ""),
            visitor_identity=d.get("visitor_identity", ""),
        )

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content, "ts": time.time()})
        self.updated_at = time.time()

    def auto_title(self) -> None:
        if self.title != "新调解对话":
            return
        for m in self.messages:
            if m["role"] == "user":
                text = m["content"][:20]
                if len(m["content"]) > 20:
                    text += "…"
                self.title = text
                return


class MediationSessionManager:
    def __init__(self, directory: str = SESSION_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def save(self, session: MediationSession) -> None:
        with open(self._path(session.id), "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, sid: str) -> MediationSession | None:
        p = self._path(sid)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return MediationSession.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load mediation session %s: %s", sid, e)
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

    def create(self) -> MediationSession:
        s = MediationSession()
        self.save(s)
        return s


class ConflictMediator:
    """AI conflict mediator with trained partner model integration."""

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
        twin_mode: str = "self",
        thinking_model: str = "",
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

        self._digest: str | None = None
        self._system_prompt: str | None = None
        self._ready = threading.Event()

        self._start_preload()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _start_preload(self) -> None:
        def _work():
            try:
                self._digest = self._load_or_build_digest()
                self._system_prompt = self._build_system_prompt()
                logger.info("Mediator ready (digest %d chars)", len(self._digest))
            except Exception:
                logger.exception("Mediator preload failed")
                self._system_prompt = MEDIATOR_SYSTEM_PROMPT.format(
                    identity_block="", partner_model_block="", digest="",
                )
            finally:
                self._ready.set()

        threading.Thread(target=_work, daemon=True).start()

    def _build_system_prompt(self) -> str:
        partner_block = ""
        if self.thinking_model:
            partner_block = (
                "你还有一个特殊能力：你读过对象的思维模型训练数据，理解TA的思考方式。\n"
                "当来访者不理解对方为什么那样做时，你可以用「根据我对TA的了解…」来还原对方可能的心理过程。\n"
                "不要大段引用，用你自己的话转述。以下是对象的核心思维模式：\n\n"
                f"{self.thinking_model[:2000]}"
            )

        digest_block = ""
        if self._digest:
            digest_block = (
                "你掌握的这对情侣的背景（在相关时自然提及，不要一次倒出来）：\n"
                f"{self._digest}"
            )

        return MEDIATOR_SYSTEM_PROMPT.format(
            identity_block="",
            partner_model_block=partner_block,
            digest=digest_block,
        )

    def _load_or_build_digest(self) -> str:
        if DIGEST_CACHE_PATH.exists():
            try:
                data = json.loads(DIGEST_CACHE_PATH.read_text(encoding="utf-8"))
                if data.get("twin_mode") == self.twin_mode and data.get("digest"):
                    logger.info("Loaded cached mediator digest")
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
        if self.twin_mode == "partner":
            parts.append("训练模式：训练对象的分身")
        else:
            parts.append("训练模式：训练本人的分身")

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
        prompt = digest_prompt(raw_context[:6000])
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
    # Chat — no auto-replies, identity detected passively
    # ------------------------------------------------------------------

    def chat(self, user_message: str, session: MediationSession) -> str:
        if not user_message:
            return ""

        self._ready.wait(timeout=120)

        if not session.visitor_identity:
            identity = self._extract_identity(user_message)
            if identity:
                session.visitor_identity = identity

        session.add_message("user", user_message)

        system = self._system_prompt or MEDIATOR_SYSTEM_PROMPT.format(
            identity_block="", partner_model_block="", digest="",
        )

        if session.visitor_identity:
            system += f"\n\n来访者身份：{session.visitor_identity}。从TA的视角出发共情，同时帮TA理解另一方。"

        history = self._build_history_window(session)

        api_messages: list[dict] = [{"role": "system", "content": system}]
        api_messages.extend(history)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                temperature=0.85,
                max_tokens=500,
            )
            reply = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.exception("Mediation LLM call failed")
            reply = f"不好意思，出了点问题 😔（{e}）"

        session.add_message("assistant", reply)
        return reply

    def _extract_identity(self, text: str) -> str:
        t = text.strip().lower()
        male_kw = re.compile(r"男方|男生|男朋友|老公|男的|男友|先生|丈夫|我是他|我是男")
        female_kw = re.compile(r"女方|女生|女朋友|老婆|女的|女友|太太|妻子|我是她|我是女")
        if male_kw.search(t):
            return "男方"
        if female_kw.search(t):
            return "女方"
        return ""

    # ------------------------------------------------------------------
    # History sliding window
    # ------------------------------------------------------------------

    def _build_history_window(self, session: MediationSession) -> list[dict]:
        all_msgs = session.messages
        if len(all_msgs) <= MAX_HISTORY_TURNS:
            return [{"role": m["role"], "content": m["content"]} for m in all_msgs]

        old_msgs = all_msgs[:-SUMMARY_KEEP_RECENT]
        recent_msgs = all_msgs[-SUMMARY_KEEP_RECENT:]

        if not session.history_summary:
            session.history_summary = self._summarize_history(old_msgs)

        result: list[dict] = []
        if session.history_summary:
            result.append({"role": "system", "content": f"[前面聊过的要点] {session.history_summary}"})
        for m in recent_msgs:
            result.append({"role": m["role"], "content": m["content"]})
        return result

    def _summarize_history(self, messages: list[dict]) -> str:
        text = "\n".join(
            f"{'来访者' if m['role'] == 'user' else 'KK'}: {m['content'][:100]}"
            for m in messages
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user",
                           "content": f"用100字概括这段咨询对话的要点和来访者的核心诉求：\n{text[:3000]}"}],
                temperature=0.2,
                max_tokens=200,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            return ""
