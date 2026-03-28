"""Shared training pipeline extracted from app.py.

Both _step3_pipeline (decrypt + train) and _import_pipeline (train only) share
the same core steps.  TrainingPipeline exposes each step as a standalone method
and also a `run_full()` entry-point that chains them all.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.data.decrypt import DecryptStep as DS
from src.data.decrypt import WeChatDecryptor
from src.data.cleaner import MessageCleaner
from src.data.conversation_builder import ConversationBuilder
from src.memory.embedder import TextEmbedder
from src.memory.vector_store import VectorStore
from src.personality.analyzer import PersonalityAnalyzer
from src.personality.emotion_analyzer import EmotionAnalyzer
from src.personality.emotion_tracker import EmotionTracker
from src.personality.thinking_profiler import ThinkingProfiler
from src.personality.prompt_builder import PromptBuilder
from src.belief.extractor import BeliefExtractor
from src.belief.graph import BeliefGraph
from src.engine.learning import LearningLoop
from src.memory.memory_bank import MemoryBank

if TYPE_CHECKING:
    from openai import OpenAI as OpenAIClient

logger = logging.getLogger(__name__)

# Module-level globals set by app.py; accessed inside pipeline methods.
_contact_registry = None


def set_contact_registry(cr) -> None:
    global _contact_registry
    _contact_registry = cr


# ---------------------------------------------------------------------------
# Helpers (mirror the ones defined in app.py so this module is self-contained)
# ---------------------------------------------------------------------------

def _timed(runner, fn, pending_fn, interval=15):
    """Run *fn()* in a sub-thread; update *runner* with elapsed-time messages.

    *pending_fn(elapsed_seconds)* returns the step object to display while waiting.
    Returns *fn()*'s return value; re-raises exceptions from *fn*.
    """
    box = [None, None]

    def _w():
        try:
            box[0] = fn()
        except Exception as exc:
            box[1] = exc

    t = threading.Thread(target=_w, daemon=True)
    t.start()
    elapsed = 0
    while t.is_alive():
        t.join(timeout=interval)
        if t.is_alive():
            elapsed += interval
            runner.update(pending_fn(elapsed))
    if box[1] is not None:
        raise box[1]
    return box[0]


def _retry_api(fn, runner, label, max_retries=3, backoff=10):
    """Run *fn()* with retries on transient API errors (502, 503, timeout, etc.)."""
    import time as _rt
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            is_transient = any(
                k in str(exc).lower()
                for k in ("502", "503", "504", "upstream", "timeout", "rate")
            )
            if attempt < max_retries and is_transient:
                wait = backoff * attempt
                runner.update("{} 第{}次请求失败 ({}), {}秒后重试…".format(
                    label, attempt, type(exc).__name__, wait))
                _rt.sleep(wait)
            else:
                raise


def _get_db_mtime(config: dict) -> float:
    """Get the latest mtime of raw DB files — used to decide if checkpoints are stale."""
    raw_dir = Path(config["paths"]["raw_db_dir"])
    if not raw_dir.exists():
        return 0
    mtimes = [f.stat().st_mtime for f in raw_dir.rglob("*.db") if f.is_file()]
    return max(mtimes) if mtimes else 0


def _ckpt_valid(path, db_mt, min_size=50) -> bool:
    """Return True if *path* exists, is bigger than *min_size*, and newer than *db_mt*."""
    p = Path(path)
    return p.exists() and p.stat().st_size >= min_size and p.stat().st_mtime > db_mt


# ---------------------------------------------------------------------------
# TrainingPipeline
# ---------------------------------------------------------------------------

class TrainingPipeline:
    """Executable training pipeline with state preserved across steps.

    Parameters
    ----------
    components : dict
        Fully-initialised component dict from app.py (parser, cleaner, builder,
        embedder, vector_store, retriever, analyzer, belief_graph,
        belief_extractor, chat_engine, emotion_tracker, memory_bank,
        learning_loop, config, …).
    contact_registry : ContactRegistry | None
        Reference to the global contact registry so step-6 analysis can
        pass it to ThinkingProfiler.extract_emotion_boundaries.
    use_twin_mode : bool
        Passed through to ConversationBuilder / analysis methods.
    """

    PARTNER_MIN_TRAIN_MESSAGES = 30

    def __init__(self, components: dict, contact_registry=None, use_twin_mode: bool = True):
        self.c = components          # component dict
        self.config = components["config"]
        self.cr = contact_registry   # ContactRegistry (may be None at init)

        # --- mutable pipeline state ---
        self._messages: list[dict] = []
        self._cleaned_all: list[dict] = []
        self._cleaned_partner: list[dict] = []
        self._conversations: list[dict] = []
        self._profile: dict = {}
        self._emo_profile: dict = {}
        self._thinking: str = ""
        self._cog_profile: dict = {}
        self._emo_boundaries: list = []
        self._emo_expression: dict = {}
        self._twin_mode: str = "self" if use_twin_mode else "partner"
        self._twin_label: str = "自己" if self._twin_mode == "self" else "对象"
        self._db_mt: float = 0.0
        self._skipped: int = 0

    # ------------------------------------------------------------------
    # Step 1 — Decrypt DB
    # ------------------------------------------------------------------

    def _step1_decrypt(self, db_path: str, wxid: str) -> DS:
        """Decrypt WeChat databases and verify the partner's message DB exists.

        Parameters
        ----------
        db_path : str
            Output directory for decrypted DBs (e.g. ``data/raw``).
        wxid : str
            Partner wxid — used only to check that their message DB was decrypted.

        Returns
        -------
        DS
            ok=False aborts the pipeline; ok=True means decryption succeeded.
        """
        keys_file = Path("vendor/wechat-decrypt/all_keys.json").resolve()
        if not keys_file.exists():
            return DS("检查密钥", False, "未找到密钥文件，请先完成第 2 步")

        try:
            kdata = yaml.safe_load(open(keys_file)) or {}
            count = len(kdata) if isinstance(kdata, dict) else 0
            step = DS("检查密钥", True, "{} 个密钥".format(count))
        except Exception as e:
            return DS("检查密钥", False, str(e))

        dec = WeChatDecryptor(output_dir=db_path)
        result = dec.decrypt_databases()
        return result

    # ------------------------------------------------------------------
    # Step 2 — Parse messages
    # ------------------------------------------------------------------

    def _step2_parse(self, ds: DS) -> DS:
        """Read all text messages from the parsed DB.

        Parameters
        ----------
        ds : DS
            The step-1 result.  If ds.ok is False the pipeline is already
            aborted and this method returns a failure step.

        Returns
        -------
        DS
            ok=False aborts.  On success ds.message contains the message count.
        """
        if not ds.ok:
            return ds

        # Support pre-loaded messages (skip_steps=2 path from _import_pipeline)
        if self._messages:
            return DS("读取消息", True, "{:,} 条文本消息（已预加载）".format(len(self._messages)))

        c = self.c
        self.config = c["config"]
        c["parser"].set_db_dir(self.config["paths"].get("raw_db_dir", "data/raw"))

        messages = c["parser"].get_all_text_messages()
        if not messages:
            return DS("读取消息", False, "未找到消息，解密可能未生成有效数据库")
        self._messages = messages
        return DS("读取消息", True, "{:,} 条文本消息".format(len(messages)))

    # ------------------------------------------------------------------
    # Step 3 — Clean messages
    # ------------------------------------------------------------------

    def _step3_clean(self, ds: DS) -> DS:
        """Clean raw messages and filter to the partner's conversation.

        Parameters
        ----------
        ds : DS
            Step-2 result.

        Returns
        -------
        DS
            ok=False aborts if the partner has too few messages.
            ds.detail carries the cleaner stats string for logging.
        """
        if not ds.ok:
            return ds

        from src.data.partner_config import load_partner_wxid, load_twin_mode
        pw = load_partner_wxid().strip()
        if not pw:
            return DS("确认对象", False, "请先在「选择 TA」中扫描并保存对象")

        self._twin_mode = load_twin_mode()
        self._twin_label = "自己" if self._twin_mode == "self" else "对象"

        cleaned_all = self.c["cleaner"].clean_messages(self._messages)
        self._cleaned_all = cleaned_all
        cleaned = [m for m in cleaned_all if m.get("StrTalker") == pw]
        self._cleaned_partner = cleaned

        if len(cleaned) < self.PARTNER_MIN_TRAIN_MESSAGES:
            return DS(
                "对象会话", False,
                "与对象的清洗后消息仅 {:,} 条（至少需要 {} 条），"
                "请确认选对人或先多聊一些".format(len(cleaned), self.PARTNER_MIN_TRAIN_MESSAGES),
            )

        cs = self.c["cleaner"].last_stats
        parts = []
        if cs and cs.dropped_binary:
            parts.append("二进制{}".format(cs.dropped_binary))
        if cs and cs.dropped_system:
            parts.append("系统消息{}".format(cs.dropped_system))
        if cs and cs.dropped_pure_emoji:
            parts.append("纯表情{}".format(cs.dropped_pure_emoji))
        if cs and cs.dropped_pure_url:
            parts.append("纯链接{}".format(cs.dropped_pure_url))
        if cs and cs.dropped_too_short:
            parts.append("过短{}".format(cs.dropped_too_short))
        if cs and cs.stripped_wxid_prefix:
            parts.append("群聊wxid前缀清除{}".format(cs.stripped_wxid_prefix))
        if cs and cs.redacted_pii:
            parts.append("PII脱敏{}".format(cs.redacted_pii))

        detail = "、".join(parts) if parts else ""
        msg = (
            "全库清洗 {:,} 条 → **仅对象** {:,} 条（过滤 {:,} 条非对象）".format(
                len(cleaned_all), len(cleaned), len(cleaned_all) - len(cleaned),
            )
            + ("（" + detail + "）" if detail else "")
        )
        return DS("数据清洗", True, msg, detail=detail)

    # ------------------------------------------------------------------
    # Step 4 — Build conversation structure
    # ------------------------------------------------------------------

    def _step4_build_conversations(self, ds: DS) -> DS:
        """Split cleaned messages into conversational chunks / turns.

        Parameters
        ----------
        ds : DS
            Step-3 result.

        Returns
        -------
        DS
        """
        if not ds.ok:
            return ds

        self.c["builder"].twin_mode = self._twin_mode
        conversations = self.c["builder"].build_conversations(self._cleaned_partner)
        for conv in conversations:
            conv["turn_count"] = len(conv.get("turns", []))
        self._conversations = conversations
        return DS(
            "构建对话段", True,
            "{:,} 段对话（{} 侧为主角）".format(len(conversations), self._twin_label),
        )

    # ------------------------------------------------------------------
    # Step 5 — Embed & vectorise
    # ------------------------------------------------------------------

    def _step5_embed(self, ds: DS, components: dict, runner=None) -> DS:
        """Download the embedding model (if needed) and write conversation vectors.

        Parameters
        ----------
        ds : DS
            Step-4 result.
        components : dict
            Same component dict passed to __init__ (kept as parameter to avoid
            circular state when called from run_full).

        Returns
        -------
        DS
            ok=False only for network/download failures.
        """
        if not ds.ok:
            return ds

        self._db_mt = _get_db_mtime(self.config)

        # Embedding model
        emb = components["embedder"]
        if emb.is_model_cached():
            pass  # already reported by caller (Step 6 will log "已就绪")
        else:
            if runner is not None:
                runner.update(DS("嵌入模型", True, "正在下载嵌入模型…"))
            try:
                emb.download_model()
            except Exception:
                logger.exception("Embedding model download failed")
                return DS("嵌入模型", False, "嵌入模型下载失败，请检查网络连接")

        # Vectorisation
        vec_count = components["vector_store"].count()
        chroma_sqlite = Path(self.config["paths"]["chroma_dir"]) / "chroma.sqlite3"
        if vec_count > 0 and _ckpt_valid(chroma_sqlite, self._db_mt, min_size=1000):
            self._skipped += 1
            return DS("向量化存储", True, "已有 {:,} 段，跳过 ⏩".format(vec_count))
        else:
            try:
                components["vector_store"].add_conversations(
                    self._conversations, components["embedder"])
                return DS(
                    "向量化存储", True,
                    "向量库共 {:,} 段".format(components["vector_store"].count()),
                )
            except Exception:
                logger.exception("Vector store write failed")
                return DS("向量化存储", False, "向量化写入失败，请检查存储空间或 chroma 服务状态")

    # ------------------------------------------------------------------
    # Step 6 — Run analysis (personality, emotion, cognitive, beliefs)
    # ------------------------------------------------------------------

    def _step6_analyze(self, ds: DS, components: dict, runner=None) -> DS:
        """Run all analysis stages and update the in-process components.

        This is the heaviest step.  It includes:
          - Personality profile generation
          - Emotion profile training + EmotionTracker replacement
          - Thinking model training
          - Cognitive profile extraction
          - Emotion-boundary extraction
          - Emotion-expression extraction
          - PromptBuilder regeneration
          - ChatEngine component refresh
          - Belief graph batch extraction
          - Memory bank batch extraction
          - Contact-registry rebuild

        Parameters
        ----------
        ds : DS
            Step-5 result.
        components : dict
            Component dict (may be updated in-place with new emotion_tracker,
            prompt_builder, memory_bank references).

        Returns
        -------
        DS
            Always ok=True; failures in sub-steps are logged individually
            and returned as DS.ok=True with warning messages.
        """
        if not ds.ok:
            return ds

        from src.personality.prompt_builder import PromptBuilder
        from openai import OpenAI as OpenAIClient

        _runner = runner if runner is not None else _NoOpRunner()

        api_cfg = self.config.get("api", {})
        profile = self._profile
        cleaned = self._cleaned_partner
        conversations = self._conversations
        db_mt = self._db_mt
        twin_mode = self._twin_mode
        twin_label = self._twin_label
        skipped = 0

        # --- Personality ---
        persona_path = Path(self.config["paths"]["persona_file"])
        _needs_regen = not _ckpt_valid(persona_path, db_mt)
        if not _needs_regen:
            profile = yaml.safe_load(open(persona_path, encoding="utf-8")) or {}
            if not profile.get("vocab_bank"):
                _needs_regen = True
        if not _needs_regen:
            self._skipped += 1
            _runner.add("⏩ 人格模型")
        else:
            profile = components["analyzer"].analyze(cleaned, twin_mode=twin_mode)
            persona_path.parent.mkdir(parents=True, exist_ok=True)
            with open(persona_path, "w", encoding="utf-8") as f:
                yaml.dump(profile, f, allow_unicode=True)
        self._profile = profile

        # --- Emotion profile ---
        emo_path = Path(self.config["paths"].get("emotion_file", "data/emotion_profile.yaml"))
        if _ckpt_valid(emo_path, db_mt):
            self._emo_profile = yaml.safe_load(open(emo_path, encoding="utf-8")) or {}
            self._skipped += 1
            _runner.add("⏩ 情绪模型")
        else:
            emo_a = EmotionAnalyzer()
            self._emo_profile = emo_a.train(cleaned, twin_mode=twin_mode)
            emo_a.save(str(emo_path))
        _emo_client = OpenAIClient(
            api_key=api_cfg.get("api_key", ""),
            base_url=api_cfg.get("base_url"),
            default_headers=api_cfg.get("headers", {}),
        )
        components["emotion_tracker"] = EmotionTracker(
            self._emo_profile, api_client=_emo_client,
            model=api_cfg.get("model", "gpt-4o"),
        )

        # --- Thinking model ---
        think_path = Path(self.config["paths"].get("thinking_model_file", "data/thinking_model.txt"))
        if _ckpt_valid(think_path, db_mt):
            self._thinking = think_path.read_text(encoding="utf-8")
            self._skipped += 1
            _runner.add("⏩ 思维模型")
        else:
            _thinking = ""
            try:
                tp_client = OpenAIClient(
                    api_key=api_cfg.get("api_key", ""),
                    base_url=api_cfg.get("base_url"),
                    default_headers=api_cfg.get("headers", {}),
                )
                tp = ThinkingProfiler(tp_client, api_cfg.get("model", "gpt-4o"))
                _thinking = _retry_api(
                    lambda: tp.train(conversations),
                    _runner, "⚠ 思维训练",
                )
                _thinking = _thinking or ""
                tp.save(_thinking, str(think_path))
                self._thinking = _thinking
            except Exception as e:
                logger.warning("Thinking profiler training failed: %s", e)
                self._thinking = ""

        # --- Cognitive profile ---
        cog_profile = {}
        try:
            _cog_path = Path("data/cognitive_profile.json")
            if not _ckpt_valid(_cog_path, db_mt):
                cog_client = OpenAIClient(
                    api_key=api_cfg.get("api_key", ""),
                    base_url=api_cfg.get("base_url"),
                    default_headers=api_cfg.get("headers", {}),
                )
                tp_cog = ThinkingProfiler(cog_client, api_cfg.get("model", "gpt-4o"))
                cog_profile = _retry_api(
                    lambda: tp_cog.extract_cognitive_profile(conversations),
                    _runner, "⚠ 认知参数",
                )
                cog_profile = cog_profile or {}
                if cog_profile:
                    ThinkingProfiler.save_cognitive_profile(cog_profile)
            else:
                cog_profile = ThinkingProfiler.load_cognitive_profile()
                self._skipped += 1
                _runner.add("⏩ 认知参数")
        except Exception as e:
            logger.warning("Cognitive profile extraction failed: %s", e)
        self._cog_profile = cog_profile

        # --- Emotion boundaries ---
        emo_boundaries = []
        try:
            _eb_path = Path("data/emotion_boundaries.json")
            if not _ckpt_valid(_eb_path, db_mt):
                eb_client = OpenAIClient(
                    api_key=api_cfg.get("api_key", ""),
                    base_url=api_cfg.get("base_url"),
                    default_headers=api_cfg.get("headers", {}),
                )
                tp_eb = ThinkingProfiler(eb_client, api_cfg.get("model", "gpt-4o"))
                emo_boundaries = _retry_api(
                    lambda: tp_eb.extract_emotion_boundaries(
                        conversations, contact_registry=_contact_registry),
                    _runner, "⚠ 情绪边界",
                )
                emo_boundaries = emo_boundaries or {}
                if emo_boundaries:
                    ThinkingProfiler.save_emotion_boundaries(emo_boundaries)
            else:
                emo_boundaries = ThinkingProfiler.load_emotion_boundaries()
                self._skipped += 1
                _runner.add("⏩ 情绪边界")
        except Exception as e:
            logger.warning("Emotion boundary extraction failed: %s", e)
        self._emo_boundaries = emo_boundaries

        # --- Emotion expression ---
        emo_expression = {}
        try:
            _expr_path = Path("data/emotion_expression.json")
            if not _ckpt_valid(_expr_path, db_mt):
                expr_client = OpenAIClient(
                    api_key=api_cfg.get("api_key", ""),
                    base_url=api_cfg.get("base_url"),
                    default_headers=api_cfg.get("headers", {}),
                )
                tp_expr = ThinkingProfiler(expr_client, api_cfg.get("model", "gpt-4o"))
                emo_expression = _retry_api(
                    lambda: tp_expr.extract_emotion_expression_style(conversations),
                    _runner, "⚠ 情绪表达",
                )
                emo_expression = emo_expression or {}
                if emo_expression:
                    ThinkingProfiler.save_emotion_expression(emo_expression)
            else:
                emo_expression = ThinkingProfiler.load_emotion_expression()
                self._skipped += 1
                _runner.add("⏩ 情绪表达")
        except Exception as e:
            logger.warning("Emotion expression extraction failed: %s", e)
        self._emo_expression = emo_expression

        # --- Prompt builder ---
        components["prompt_builder"] = PromptBuilder(
            persona_profile=self._profile,
            cold_start_description=self.config.get("cold_start_description", ""),
            thinking_model=self._thinking,
            cognitive_profile=self._cog_profile,
            emotion_boundaries=self._emo_boundaries,
            emotion_expression=self._emo_expression,
        )
        components["prompt_builder"].regenerate_guidance()
        _runner.update("✓ 指引文件已生成")

        # --- Chat engine refresh ---
        components["chat_engine"].set_components(
            components["retriever"],
            components["belief_graph"],
            components["prompt_builder"],
            components["vector_store"],
            components["emotion_tracker"],
            memory_bank=components.get("memory_bank"),
        )

        # --- Belief graph ---
        bg = components["belief_graph"]
        beliefs_path = Path(self.config["paths"]["beliefs_file"])
        if bg.count() > 0 and _ckpt_valid(beliefs_path, db_mt, min_size=100):
            self._skipped += 1
            _runner.add("⏩ 信念图谱")
        else:
            old_count = bg.count()
            bg.beliefs.clear()
            bg.contradictions.clear()
            bg._embeddings.clear()
            bg._next_id = 1
            bg.save()
            ll = components["learning_loop"]
            try:
                ll.batch_extract_beliefs(conversations, top_n_contacts=1, samples_per_contact=20)
            except Exception as e:
                logger.warning("Belief extraction failed: %s", e)

        # --- Memory bank ---
        mb = components.get("memory_bank")
        if mb is None:
            mb = MemoryBank(
                filepath="data/memories.json",
                embedder=components["embedder"],
            )
            components["memory_bank"] = mb
        mem_path = Path("data/memories.json")
        if mb.count() > 0 and _ckpt_valid(mem_path, db_mt, min_size=10):
            self._skipped += 1
            _runner.add("⏩ 记忆库")
        else:
            mb.clear()
            mb_client = OpenAIClient(
                api_key=api_cfg.get("api_key", ""),
                base_url=api_cfg.get("base_url"),
                default_headers=api_cfg.get("headers", {}),
            )
            try:
                mb.batch_extract(
                    conversations, mb_client, api_cfg.get("model", "gpt-4o"))
            except Exception as e:
                logger.warning("Memory extraction failed: %s", e)

        # --- Contact registry ---
        from src.data.partner_config import load_partner_wxid
        pw = load_partner_wxid().strip()
        contacts_path = Path("data/contacts.json")
        if _ckpt_valid(contacts_path, db_mt, min_size=10):
            self._skipped += 1
            _runner.add("⏩ 联系人")
        else:
            try:
                global _contact_registry
                if _contact_registry is None:
                    from src.data.contact_registry import ContactRegistry
                    _contact_registry = ContactRegistry()
                contacts_db = components["parser"].get_contacts()
                _contact_registry.build_from_messages(self._messages, contacts_db)
                if pw in _contact_registry.contacts:
                    style = components["analyzer"].analyze_per_contact(cleaned, pw)
                    if style:
                        _contact_registry.set_chat_style(pw, style)
            except Exception as e:
                logger.warning("Contact registry build failed: %s", e)

        # --- Critical file check ---
        critical_missing = []
        for label, path in [
            ("思维模型", "data/thinking_model.txt"),
            ("认知参数", "data/cognitive_profile.json"),
            ("情绪边界", "data/emotion_boundaries.json"),
            ("情绪表达", "data/emotion_expression.json"),
        ]:
            if not Path(path).exists() or Path(path).stat().st_size < 50:
                critical_missing.append(label)

        return DS(
            "学习完成",
            True,
            ("跳过 {} 个已完成步骤 ⏩" if skipped else "所有步骤完成，请前往「校准」进一步校准")
            if not critical_missing else
            "以下关键步骤因 API 错误未完成：{}。请检查 API 后重新训练。".format(
                "、".join(critical_missing)),
        )

    # ------------------------------------------------------------------
    # Convenience getters (used by callers that want intermediate state)
    # ------------------------------------------------------------------

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def conversations(self) -> list[dict]:
        return self._conversations

    @property
    def profile(self) -> dict:
        return self._profile

    @property
    def twin_mode(self) -> str:
        return self._twin_mode

    @property
    def twin_label(self) -> str:
        return self._twin_label

    # ------------------------------------------------------------------
    # run_full — chain all steps with _timed wrappers
    # ------------------------------------------------------------------

    def run_full(
        self,
        db_path: str,
        wxid: str,
        partner_wxid: str,
        components: dict,
        use_twin_mode: bool = True,
        runner=None,
        skip_steps: int = 0,
    ) -> tuple[bool, str]:
        """Execute the full pipeline (steps 1-6), handling threading and errors.

        Parameters
        ----------
        db_path : str
            Directory for decrypted DBs (passed to step 1).
        wxid : str
            Partner wxid (passed to step 1).
        partner_wxid : str
            Current partner wxid from partner_config (used for filtering / checking).
        components : dict
            Component dict (same object as self.c; updated in-place by step 6).
        use_twin_mode : bool
            Twin-mode flag for ConversationBuilder.
        runner : TrainingRunner | None
            The app.py TrainingRunner instance.  If None a _NoOpRunner is used
            (so step methods that need a runner still work outside the Gradio
            context).

        Returns
        -------
        tuple[bool, str]
            (success, final_message).
        """
        if runner is None:
            runner = _NoOpRunner()

        twin_mode_flag = use_twin_mode
        from src.data.partner_config import load_twin_mode
        twin_mode_actual = load_twin_mode()
        twin_label = "自己" if twin_mode_actual == "self" else "对象"
        self._twin_mode = twin_mode_actual
        self._twin_label = twin_label

        self._db_mt = _get_db_mtime(self.config)

        # ── Step 1 (skip if caller pre-loaded state) ─────────────────────
        if skip_steps <= 1:
            try:
                ds1 = self._step1_decrypt(db_path, wxid)
            except Exception as exc:
                logger.exception("[PIPELINE] Step 1 crashed: %s", exc)
                return False, "Step 1 (解密) 异常: {}".format(exc)
            runner.add(ds1)
            if not ds1.ok:
                return False, ds1.message
        else:
            ds1 = DS("检查密钥", True, "跳过（已解密）")
            runner.add(ds1)

        # ── Step 2 ──────────────────────────────────────────────────────
        if skip_steps <= 2:
            try:
                ds2 = self._step2_parse(ds1)
            except Exception as exc:
                logger.exception("[PIPELINE] Step 2 crashed: %s", exc)
                return False, "Step 2 (读取消息) 异常: {}".format(exc)
            runner.update(ds2)
            if not ds2.ok:
                return False, ds2.message
        else:
            ds2 = DS("读取消息", True, "跳过（已加载 {:,} 条）".format(len(self._messages)))
            runner.update(ds2)

        # ── Step 3 ──────────────────────────────────────────────────────
        try:
            ds3 = self._step3_clean(ds2)
        except Exception as exc:
            logger.exception("[PIPELINE] Step 3 crashed: %s", exc)
            return False, "Step 3 (数据清洗) 异常: {}".format(exc)
        runner.add(ds3)
        if not ds3.ok:
            return False, ds3.message

        # ── Step 4 ──────────────────────────────────────────────────────
        try:
            ds4 = self._step4_build_conversations(ds3)
        except Exception as exc:
            logger.exception("[PIPELINE] Step 4 crashed: %s", exc)
            return False, "Step 4 (构建对话) 异常: {}".format(exc)
        runner.add(ds4)
        if not ds4.ok:
            return False, ds4.message

        # ── Step 5 ──────────────────────────────────────────────────────
        def _do_embed():
            return self._step5_embed(ds4, components, runner=runner)

        try:
            ds5 = _timed(
                runner,
                _do_embed,
                lambda e: DS("向量化存储", True, "写入中… 已等待 {}s".format(e)),
            )
        except Exception as exc:
            logger.exception("[PIPELINE] Step 5 crashed: %s", exc)
            return False, "Step 5 (向量化) 异常: {}".format(exc)
        runner.update(ds5)
        if not ds5.ok:
            return False, ds5.message

        # ── Step 6 ──────────────────────────────────────────────────────
        try:
            ds6 = self._step6_analyze(ds5, components, runner=runner)
        except Exception as exc:
            logger.exception("[PIPELINE] Step 6 crashed: %s", exc)
            return False, "Step 6 (分析) 异常: {}".format(exc)
        runner.add(ds6)

        critical_missing = []
        for label, path in [
            ("思维模型", "data/thinking_model.txt"),
            ("认知参数", "data/cognitive_profile.json"),
            ("情绪边界", "data/emotion_boundaries.json"),
            ("情绪表达", "data/emotion_expression.json"),
        ]:
            if not Path(path).exists() or Path(path).stat().st_size < 50:
                critical_missing.append(label)

        if critical_missing:
            runner.error = "关键步骤失败: " + "、".join(critical_missing)
            return False, runner.error

        return True, ds6.message


# ---------------------------------------------------------------------------
# _NoOpRunner — used when TrainingPipeline.run_full() is called outside the
# Gradio / TrainingRunner context (e.g. in tests or standalone scripts)
# ---------------------------------------------------------------------------

class _NoOpRunner:
    """Minimal runner stand-in that discards all add/update calls."""

    error: str | None = None

    def add(self, step):
        logger.info("[PIPELINE] %s", step)

    def update(self, step):
        logger.info("[PIPELINE] %s", step)

    def get_steps(self):
        return []

    def is_running(self):
        return False
