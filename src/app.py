from __future__ import annotations

import os as _os, sys as _sys
_project_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _project_root not in _sys.path:
    _sys.path.insert(0, _project_root)
_os.chdir(_project_root)

import json
import logging
import random
import threading
import time as _time
from pathlib import Path

import yaml

# Monkeypatch gradio_client bug on Python 3.9: `if "const" in schema` crashes
# when schema is a bool instead of a dict.
import gradio_client.utils as _gc_utils
_orig_get_type = _gc_utils.get_type
def _patched_get_type(schema):
    if not isinstance(schema, dict):
        return "Any"
    return _orig_get_type(schema)
_gc_utils.get_type = _patched_get_type

_orig_json_schema = _gc_utils._json_schema_to_python_type
def _patched_json_schema(schema, defs=None):
    if not isinstance(schema, dict):
        return "Any"
    return _orig_json_schema(schema, defs)
_gc_utils._json_schema_to_python_type = _patched_json_schema

import gradio as gr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

# Paths resolved relative to this source file — not cwd
_APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = _APP_DIR / "config.yaml"
CONFIG_EXAMPLE = _APP_DIR / "config.example.yaml"

# ---------------------------------------------------------------------------
# Initialization (lazy — no heavy model loading at import time)
# ---------------------------------------------------------------------------

components: dict | None = None
init_error: str | None = None
contact_registry = None
MIN_CALIBRATION_TASKS = 5

# --- 情侣分身版 ---
PARTNER_PERSONA_SELF_ID = "couple_self"
PARTNER_PERSONA_PARTNER_ID = "couple_partner"
PARTNER_MIN_TRAIN_MESSAGES = 30


def ensure_couple_personas() -> None:
    """创建固定的「个人模式 / 对象模式」人格文件（若不存在）。"""
    global persona_mgr
    if persona_mgr is None:
        return
    from src.engine.persona import Persona, RELATIONSHIP_TYPES as _RT
    if persona_mgr.load(PARTNER_PERSONA_SELF_ID) is None:
        persona_mgr.save(Persona(
            id=PARTNER_PERSONA_SELF_ID,
            name="",
            relationship="self",
            label=_RT["self"],
            background="",
        ))
    if persona_mgr.load(PARTNER_PERSONA_PARTNER_ID) is None:
        persona_mgr.save(Persona(
            id=PARTNER_PERSONA_PARTNER_ID,
            name="",
            relationship="partner",
            label=_RT["partner"],
            background="",
        ))


def sync_partner_persona_metadata() -> None:
    """对象确认后，把备注名同步到固定对象人格。"""
    global persona_mgr, contact_registry
    if persona_mgr is None:
        return
    from src.data.partner_config import load_partner_wxid
    from src.engine.persona import Persona, RELATIONSHIP_TYPES as _RT
    pw = load_partner_wxid().strip()
    name = ""
    if contact_registry and pw:
        name = contact_registry.get_display_name(pw)
    p = persona_mgr.load(PARTNER_PERSONA_PARTNER_ID)
    if p is None:
        p = Persona(
            id=PARTNER_PERSONA_PARTNER_ID,
            name=name,
            relationship="partner",
            label=_RT["partner"],
            background="",
        )
    else:
        p.name = name
    persona_mgr.save(p)


def partner_candidate_choices() -> list[tuple[str, str]]:
    if contact_registry is None or contact_registry.count() == 0:
        return [("（请先扫描联系人）", "")]
    from src.data.partner_config import load_partner_wxid
    current = load_partner_wxid().strip()
    out: list[tuple[str, str]] = []
    for c in contact_registry.iter_partner_candidates(18):
        wxid = c["wxid"]
        nm = contact_registry.get_display_name(wxid)
        rel = contact_registry.get_relationship_label(wxid)
        cnt = c.get("message_count", 0)
        tag = " ★当前" if wxid == current else ""
        out.append(("{} · {} · {:,} 条{}".format(nm, rel, cnt, tag), wxid))
    return out or [("（无私聊联系人）", "")]


def save_partner_selection(wxid: str) -> tuple[str, object]:
    from src.data.partner_config import save_partner_wxid, load_partner_wxid
    wxid = (wxid or "").strip()
    if not wxid:
        return '<span style="color:#f87171">请从列表中选择一个联系人</span>', gr.update()
    save_partner_wxid(wxid)
    if contact_registry:
        contact_registry.set_relationship(wxid, "partner")
    sync_partner_persona_metadata()
    label = contact_registry.get_display_name(wxid) if contact_registry else wxid
    gr.Info("已确认对象：{}".format(label))
    cur = load_partner_wxid().strip()
    return (
        '<span style="color:#65a88a">✓ 已保存。训练将只使用与「{}」的聊天记录。</span>'.format(label),
        gr.update(choices=partner_candidate_choices(), value=cur or None),
    )


def save_twin_mode_selection(mode: str) -> str:
    from src.data.partner_config import save_twin_mode
    mode = (mode or "self").strip()
    save_twin_mode(mode)
    label = "训练自己的分身" if mode == "self" else "训练对象的分身"
    gr.Info("训练模式已切换：{}".format(label))
    return '<span style="color:#65a88a">✓ 当前训练模式：{}</span>'.format(label)


def _current_twin_mode() -> str:
    from src.data.partner_config import load_twin_mode
    return load_twin_mode()


def couple_mode_to_persona_id(mode: str) -> str:
    return PARTNER_PERSONA_SELF_ID if (mode or "").strip() == "self" else PARTNER_PERSONA_PARTNER_ID


# ---------------------------------------------------------------------------
# TrainingRunner — background-thread training with decoupled progress
# ---------------------------------------------------------------------------

TRAINING_STATUS_PATH = Path("data/.training_status.json")


class TrainingRunner:
    """Runs a training pipeline in a background thread.

    Progress is tracked in-memory and persisted to a JSON file so that:
    - Gradio SSE disconnects never kill training
    - Page refresh shows current progress
    - Terminal logs show every step
    """

    _instance = None

    def __init__(self):
        self.steps: list = []
        self.done = False
        self.error: str | None = None
        self.mode: str = "text"  # "text" for train_output, "html" for step3_output
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._render_fn = lambda steps: "\n".join(str(s) for s in steps)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _reset(self):
        with self._lock:
            self.steps.clear()
            self.done = False
            self.error = None
            self.mode = "text"

    def add(self, step):
        """Append a new step (thread-safe)."""
        with self._lock:
            self.steps.append(step)
        logger.info("[TRAIN] %s", step)
        self._save()

    def update(self, step):
        """Replace the last step (thread-safe)."""
        with self._lock:
            if self.steps:
                self.steps[-1] = step
            else:
                self.steps.append(step)
        self._save()

    def snapshot(self):
        with self._lock:
            return list(self.steps), self.done, self.error

    def _save(self):
        try:
            steps, done, error = self.snapshot()
            TRAINING_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            TRAINING_STATUS_PATH.write_text(json.dumps({
                "steps": [str(s) for s in steps],
                "done": done,
                "error": error,
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def start(self, pipeline_fn, render_fn=None, mode="text"):
        self._reset()
        self.mode = mode
        if render_fn:
            self._render_fn = render_fn
        self._save()
        self._thread = threading.Thread(
            target=self._worker, args=(pipeline_fn,), daemon=True,
        )
        self._thread.start()

    def _worker(self, pipeline_fn):
        try:
            pipeline_fn(self)
        except Exception as exc:
            logger.exception("[TRAIN] Pipeline crashed: %s", exc)
            self.error = str(exc)
            self.add("❌ 训练异常终止: {}".format(exc))
        finally:
            with self._lock:
                self.done = True
            self._save()
            logger.info("[TRAIN] Pipeline finished (steps=%d)", len(self.steps))

    def get_steps(self):
        """Return a copy of the current steps list (thread-safe)."""
        with self._lock:
            return list(self.steps)

    def get_progress_html(self):
        """Return current progress as a simple text summary (for page-load checks)."""
        steps, done, error = self.snapshot()
        if not steps:
            return ""
        lines = [str(s) for s in steps]
        if not done and self.is_running():
            lines.append("⏳ 训练进行中…")
        return "\n".join(lines)


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
            is_transient = any(k in str(exc).lower() for k in ("502", "503", "504", "upstream", "timeout", "rate"))
            if attempt < max_retries and is_transient:
                wait = backoff * attempt
                runner.update("{} 第{}次请求失败 ({}), {}秒后重试…".format(label, attempt, type(exc).__name__, wait))
                _rt.sleep(wait)
            else:
                raise


def _get_db_mtime(config):
    """Get the latest mtime of raw DB files — used to decide if checkpoints are stale."""
    raw_dir = Path(config["paths"]["raw_db_dir"])
    if not raw_dir.exists():
        return 0
    mtimes = [f.stat().st_mtime for f in raw_dir.rglob("*.db") if f.is_file()]
    return max(mtimes) if mtimes else 0


def _ckpt_valid(path, db_mt, min_size=50):
    """Return True if *path* exists, is bigger than *min_size*, and newer than *db_mt*."""
    p = Path(path)
    return p.exists() and p.stat().st_size >= min_size and p.stat().st_mtime > db_mt


def _resolve_env_vars(obj):
    """Recursively resolve ${VAR} and ${VAR:default} in config values."""
    import re as _re
    if isinstance(obj, str):
        def _sub(m):
            expr = m.group(1)
            if ":" in expr:
                var, default = expr.split(":", 1)
            else:
                var, default = expr, ""
            return _os.environ.get(var, default)
        return _re.sub(r"\$\{([^}]+)\}", _sub, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(i) for i in obj]
    return obj


def load_config() -> dict:
    from dotenv import load_dotenv
    # Load .env from the app directory so this works regardless of cwd
    load_dotenv(dotenv_path=str(_APP_DIR / ".env"), override=False)

    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE.exists():
            import shutil
            shutil.copy2(CONFIG_EXAMPLE, CONFIG_PATH)
            logger.info("已自动从 %s 创建 %s，请在界面中配置 API Key。", CONFIG_EXAMPLE, CONFIG_PATH)
        else:
            raise FileNotFoundError(
                f"配置文件 {CONFIG_PATH} 和示例文件 {CONFIG_EXAMPLE} 均不存在。"
            )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _resolve_env_vars(raw)


def init_components(config: dict) -> dict:
    from src.data.parser import WeChatDBParser
    from src.data.cleaner import MessageCleaner
    from src.data.conversation_builder import ConversationBuilder
    from src.memory.embedder import TextEmbedder
    from src.memory.vector_store import VectorStore
    from src.memory.retriever import MemoryRetriever
    from src.personality.analyzer import PersonalityAnalyzer
    from src.personality.prompt_builder import PromptBuilder
    from src.belief.extractor import BeliefExtractor
    from src.belief.graph import BeliefGraph
    from src.engine.chat import ChatEngine
    from src.engine.learning import LearningLoop

    paths = config["paths"]
    emb_cfg = config["embedding"]
    chunk_cfg = config["chunking"]
    ret_cfg = config["retrieval"]
    api_cfg = config["api"]

    parser = WeChatDBParser(paths["raw_db_dir"])
    cleaner = MessageCleaner()
    from src.data.partner_config import load_twin_mode as _ltm_init
    builder = ConversationBuilder(
        time_gap_minutes=chunk_cfg["time_gap_minutes"],
        max_turns=chunk_cfg["max_turns"],
        min_turns=chunk_cfg["min_turns"],
        twin_mode=_ltm_init(),
    )

    embedder = TextEmbedder(
        model_name=emb_cfg["model"],
        device=emb_cfg["device"],
        offline=emb_cfg.get("offline", True),
    )
    vector_store = VectorStore(persist_dir=paths["chroma_dir"])
    retriever = MemoryRetriever(vector_store, embedder)

    analyzer = PersonalityAnalyzer()

    persona_path = Path(paths["persona_file"])
    persona_profile: dict = {}
    if persona_path.exists():
        with open(persona_path, encoding="utf-8") as f:
            persona_profile = yaml.safe_load(f) or {}

    from src.personality.thinking_profiler import ThinkingProfiler
    thinking_model = ThinkingProfiler.load(paths.get("thinking_model_file", "data/thinking_model.txt"))
    cognitive_profile = ThinkingProfiler.load_cognitive_profile("data/cognitive_profile.json")
    emotion_boundaries = ThinkingProfiler.load_emotion_boundaries("data/emotion_boundaries.json")
    emotion_expression = ThinkingProfiler.load_emotion_expression("data/emotion_expression.json")

    prompt_builder = PromptBuilder(
        persona_profile=persona_profile,
        cold_start_description=config.get("cold_start_description", ""),
        thinking_model=thinking_model,
        cognitive_profile=cognitive_profile,
        emotion_boundaries=emotion_boundaries,
        emotion_expression=emotion_expression,
    )

    belief_graph = BeliefGraph(filepath=paths["beliefs_file"], embedder=embedder)
    belief_extractor = BeliefExtractor(
        api_provider=api_cfg["provider"],
        api_key=api_cfg["api_key"],
        model=api_cfg.get("extraction_model", api_cfg["model"]),
        base_url=api_cfg.get("base_url"),
        headers=api_cfg.get("headers"),
    )

    chat_engine = ChatEngine(
        {
            "api_key": api_cfg["api_key"],
            "model": api_cfg["model"],
            "provider": api_cfg["provider"],
            "base_url": api_cfg.get("base_url"),
            "headers": api_cfg.get("headers"),
            "top_k_vectors": ret_cfg["top_k_vectors"],
            "top_k_beliefs": ret_cfg["top_k_beliefs"],
        }
    )
    from src.personality.emotion_analyzer import EmotionAnalyzer
    from src.personality.emotion_tracker import EmotionTracker

    emotion_profile = EmotionAnalyzer.load(paths.get("emotion_file", "data/emotion_profile.yaml"))
    from openai import OpenAI as _OAI_init
    _emo_client = _OAI_init(
        api_key=api_cfg.get("api_key", ""),
        base_url=api_cfg.get("base_url"),
        default_headers=api_cfg.get("headers", {}),
    )
    emotion_tracker = EmotionTracker(
        emotion_profile,
        api_client=_emo_client,
        model=api_cfg.get("model", "gpt-4o"),
    )

    from src.memory.memory_bank import MemoryBank
    memory_bank = MemoryBank(
        filepath=paths.get("memories_file", "data/memories.json"),
        embedder=embedder,
    )

    chat_engine.set_components(
        retriever, belief_graph, prompt_builder, vector_store, emotion_tracker,
        memory_bank=memory_bank,
    )

    learning_loop = LearningLoop(
        belief_extractor=belief_extractor,
        belief_graph=belief_graph,
        vector_store=vector_store,
        embedder=embedder,
    )

    from src.cognitive.task_library import TaskLibrary
    from src.cognitive.inference_engine import InferenceEngine
    from src.cognitive.contradiction_detector import ContradictionDetector
    from src.cognitive.active_probe import ActiveProbe

    from openai import OpenAI as _CogOAI
    _cog_client = _CogOAI(
        api_key=api_cfg["api_key"],
        base_url=api_cfg.get("base_url"),
        default_headers=api_cfg.get("headers", {}),
    )
    _cog_model = api_cfg["model"]

    task_library = TaskLibrary(
        storage_path=paths.get("task_results_file", "data/task_results.json"),
        tasks_file=paths.get("cognitive_tasks_file", "data/cognitive_tasks.json"),
    )
    inference_engine = InferenceEngine(_cog_client, _cog_model)
    contradiction_detector = ContradictionDetector(_cog_client, _cog_model)
    active_probe = ActiveProbe(_cog_client, _cog_model)

    return {
        "config": config,
        "parser": parser,
        "cleaner": cleaner,
        "builder": builder,
        "embedder": embedder,
        "vector_store": vector_store,
        "retriever": retriever,
        "analyzer": analyzer,
        "prompt_builder": prompt_builder,
        "belief_graph": belief_graph,
        "belief_extractor": belief_extractor,
        "memory_bank": memory_bank,
        "chat_engine": chat_engine,
        "learning_loop": learning_loop,
        "emotion_tracker": emotion_tracker,
        "task_library": task_library,
        "inference_engine": inference_engine,
        "contradiction_detector": contradiction_detector,
        "active_probe": active_probe,
    }


session_mgr = None
persona_mgr = None

try:
    _cfg = load_config()
    components = init_components(_cfg)
    from src.engine.session import SessionManager
    session_mgr = SessionManager(directory="data/sessions")
    from src.engine.persona import PersonaManager, RELATIONSHIP_TYPES
    persona_mgr = PersonaManager(directory="data/personas")
    from src.data.contact_registry import ContactRegistry
    contact_registry = ContactRegistry()
    ensure_couple_personas()
    import threading
    threading.Thread(target=components["embedder"].warmup, daemon=True).start()
    logger.info("所有组件初始化完成（嵌入模型后台预热中）")
except Exception as exc:
    init_error = str(exc)
    logger.error("初始化失败: %s", init_error)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
footer { display: none !important; }

/* ================================================================
   Global — smooth rendering
   ================================================================ */
.gradio-container {
    max-width: 100% !important;
    padding: 0 !important;
    margin: 0 !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* ================================================================
   Sidebar nav — vertical sidebar from Gradio tab-nav
   ================================================================ */
#main-tabs > .tabs {
    display: flex !important;
    flex-direction: row !important;
    gap: 0 !important;
    min-height: 100vh;
}
#main-tabs > .tabs > .tab-nav {
    flex-direction: column !important;
    width: 220px !important;
    min-width: 220px !important;
    max-width: 220px !important;
    background: #f3eded;
    border-right: 1px solid #e6dcd8 !important;
    border-bottom: none !important;
    padding: 0 !important;
    margin: 0 !important;
    gap: 2px !important;
    overflow-y: auto;
    position: sticky;
    top: 0;
    align-self: flex-start;
    height: 100vh;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav { background: #1e1a1b; border-right-color: #3a3234 !important; }
}

/* Brand header — name */
#main-tabs > .tabs > .tab-nav::before {
    content: "心译";
    display: block;
    padding: 22px 16px 4px;
    font-size: 1.3em;
    font-weight: 800;
    color: #b07c84;
    letter-spacing: .02em;
    flex-shrink: 0;
}
/* Brand header — tagline */
#main-tabs > .tabs > .tab-nav::after {
    content: "发出去之前，先译一下";
    display: block;
    padding: 0 16px 18px;
    font-size: .72em;
    font-weight: 400;
    color: #8c7b7f;
    letter-spacing: .01em;
    border-bottom: 1px solid #e6dcd8;
    margin-bottom: 8px;
    flex-shrink: 0;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav::before { color: #d4a0a8; }
    #main-tabs > .tabs > .tab-nav::after { color: #a8969a; border-bottom-color: #3a3234; }
}

/* Tab buttons */
#main-tabs > .tabs > .tab-nav > button {
    text-align: left !important;
    justify-content: flex-start !important;
    border: none !important;
    border-radius: 8px !important;
    margin: 1px 8px !important;
    padding: 9px 12px !important;
    font-size: .88em !important;
    font-weight: 450 !important;
    color: #6b5a5e !important;
    background: transparent !important;
    transition: background .15s, color .15s !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
#main-tabs > .tabs > .tab-nav > button:hover {
    background: rgba(176,124,132,.08) !important;
    color: #3d2c30 !important;
}
#main-tabs > .tabs > .tab-nav > button.selected {
    background: rgba(176,124,132,.12) !important;
    color: #2a1f22 !important;
    font-weight: 550 !important;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav > button { color: #a8969a !important; }
    #main-tabs > .tabs > .tab-nav > button:hover { background: rgba(255,255,255,.06) !important; color: #e6dcd8 !important; }
    #main-tabs > .tabs > .tab-nav > button.selected { background: rgba(212,160,168,.15) !important; color: #f0e8e4 !important; }
}

/* Section separators */
#main-tabs > .tabs > .tab-nav > button:nth-child(4),
#main-tabs > .tabs > .tab-nav > button:nth-child(8) {
    margin-top: 12px !important;
    position: relative;
}
#main-tabs > .tabs > .tab-nav > button:nth-child(4)::before,
#main-tabs > .tabs > .tab-nav > button:nth-child(8)::before {
    content: "";
    position: absolute;
    top: -7px;
    left: 12px;
    right: 12px;
    height: 1px;
    background: #e6dcd8;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav > button:nth-child(4)::before,
    #main-tabs > .tabs > .tab-nav > button:nth-child(8)::before { background: #3a3234; }
}

/* System tab (last) — push to bottom */
#main-tabs > .tabs > .tab-nav > button:last-child {
    margin-top: auto !important;
    border-top: 1px solid #e6dcd8 !important;
    border-radius: 0 !important;
    padding: 12px 16px !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    margin-bottom: 0 !important;
    opacity: .7;
}

/* Tab content area */
#main-tabs > .tabs > .tabitem {
    flex: 1 !important;
    min-width: 0;
    padding: 32px 40px !important;
    overflow-y: auto;
    max-height: 100vh;
}

/* ================================================================
   Chat sidebar (session list)
   ================================================================ */
#sidebar-col {
    background: #f7f0ee;
    border-right: 1px solid #e6dcd8;
    border-radius: 0;
    padding: 4px 0 !important;
    max-width: 160px !important;
    min-width: 160px !important;
}
@media (prefers-color-scheme: dark) {
    #sidebar-col { background: #1a1617; border-right-color: #3a3234; }
}

#new-chat-btn {
    margin: 4px 6px 6px !important;
    font-size: .82em !important;
    padding: 6px 0 !important;
}

#session-radio {
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
    overflow-y: auto;
    max-height: calc(100vh - 120px);
}
#session-radio .wrap {
    gap: 1px !important;
}
#session-radio label {
    display: flex !important;
    align-items: center !important;
    padding: 8px 10px !important;
    margin: 0 4px !important;
    border-radius: 6px !important;
    font-size: .8em !important;
    cursor: pointer !important;
    transition: background .12s !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    color: #6b5a5e !important;
    border: none !important;
    background: transparent !important;
    min-height: 0 !important;
    line-height: 1.3 !important;
}
#session-radio label:hover {
    background: rgba(176,124,132,.08) !important;
}
#session-radio label.selected,
#session-radio input:checked + span {
    background: rgba(176,124,132,.14) !important;
    color: #2a1f22 !important;
    font-weight: 550 !important;
}
#session-radio input[type="radio"] {
    display: none !important;
}
@media (prefers-color-scheme: dark) {
    #session-radio label { color: #a8969a !important; }
    #session-radio label:hover { background: rgba(255,255,255,.06) !important; }
    #session-radio label.selected { background: rgba(212,160,168,.15) !important; color: #f0e8e4 !important; }
}

#del-session-btn {
    margin: 4px 6px !important;
    font-size: .72em !important;
    opacity: .5;
    padding: 4px 0 !important;
}
#del-session-btn:hover { opacity: .8; }

/* ================================================================
   Chat area
   ================================================================ */
#chat-area .chatbot { border: none !important; }
#chat-area .message { max-width: 680px; margin: 0 auto; }
#main-chatbot { border: none !important; background: transparent !important; }

#chat-input textarea {
    border-radius: 12px !important;
    padding: 10px 14px !important;
    border: 1px solid #e6dcd8 !important;
    transition: border-color .2s, box-shadow .2s !important;
}
#chat-input textarea:focus {
    border-color: #b07c84 !important;
    box-shadow: 0 0 0 3px rgba(176,124,132,.15) !important;
    outline: none !important;
}
#send-btn {
    border-radius: 50% !important;
    width: 42px !important;
    height: 42px !important;
    min-width: 42px !important;
    padding: 0 !important;
    font-size: 1.1em !important;
}

/* ================================================================
   Analytics cards
   ================================================================ */
.stat-card {
    background: var(--block-background-fill);
    border: 1px solid var(--block-border-color);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    min-height: 100px;
    transition: box-shadow .2s, transform .2s;
}
.stat-card:hover { box-shadow: 0 4px 16px rgba(61,44,48,.06); transform: translateY(-1px); }
.stat-card .stat-value { font-size: 2em; font-weight: 700; color: var(--body-text-color); margin: 4px 0; }
.stat-card .stat-label { font-size: .9em; color: var(--body-text-color-subdued); }

.step-card {
    padding: 12px 16px;
    margin: 6px 0;
    border-radius: 8px;
    border-left: 4px solid var(--block-border-color);
    background: var(--block-background-fill);
}
.step-ok { border-left-color: #65a88a; }
.step-fail { border-left-color: #ef4444; }

/* ================================================================
   Word cloud
   ================================================================ */
.wordcloud { display:flex; flex-wrap:wrap; gap:6px; justify-content:center; padding:16px; }
.wordcloud span {
    display:inline-block;
    padding: 4px 10px;
    border-radius: 6px;
    background: var(--block-background-fill);
    border: 1px solid var(--block-border-color);
    white-space: nowrap;
    transition: transform .15s;
}
.wordcloud span:hover { transform: scale(1.05); }

/* ================================================================
   Responsive — collapse sidebar on small screens
   ================================================================ */
@media (max-width: 768px) {
    #main-tabs > .tabs { flex-direction: column !important; }
    #main-tabs > .tabs > .tab-nav {
        width: 100% !important; min-width: 100% !important; max-width: 100% !important;
        flex-direction: row !important; height: auto !important; position: static;
        overflow-x: auto; border-right: none !important; border-bottom: 1px solid #e6dcd8 !important;
        padding: 8px !important;
    }
    #main-tabs > .tabs > .tab-nav::before { display: none; }
    #main-tabs > .tabs > .tab-nav::after { display: none; }
    #main-tabs > .tabs > .tab-nav > button { margin: 0 2px !important; white-space: nowrap; }
    #main-tabs > .tabs > .tab-nav > button:last-child { margin-top: 0 !important; }
    #main-tabs > .tabs > .tabitem { padding: 16px !important; max-height: none; }
}
"""


# ---------------------------------------------------------------------------
# Helper: build HTML stat cards
# ---------------------------------------------------------------------------

def _stat_card(value, label: str) -> str:
    return (
        f'<div class="stat-card">'
        f'<div class="stat-label">{label}</div>'
        f'<div class="stat-value">{value}</div>'
        f'</div>'
    )


def _step_html(steps: list) -> str:
    parts = []
    for s in steps:
        if isinstance(s, str):
            parts.append('<div class="step-card step-ok">{}</div>'.format(s))
            continue
        cls = "step-ok" if s.ok else "step-fail"
        icon = "✓" if s.ok else "✗"
        detail = "<br><small style='opacity:.6'>{}</small>".format(s.detail) if s.detail else ""
        parts.append('<div class="step-card {cls}">{icon} <b>{name}</b> — {msg}{detail}</div>'.format(
            cls=cls, icon=icon, name=s.name, msg=s.message, detail=detail,
        ))
    return "".join(parts)


def _wordcloud_html(phrases: list, max_items: int = 40) -> str:
    if not phrases:
        return "<p style='text-align:center;opacity:.5'>暂无数据</p>"

    items = phrases[:max_items]
    max_count = items[0][1] if items else 1
    tags = []
    for word, count in items:
        ratio = count / max_count
        size = 0.75 + ratio * 1.5
        opacity = 0.5 + ratio * 0.5
        tags.append(f'<span style="font-size:{size:.2f}em;opacity:{opacity:.2f}">{word}</span>')
    return f'<div class="wordcloud">{"".join(tags)}</div>'


# ---------------------------------------------------------------------------
# Callback: Persona-based chat
# ---------------------------------------------------------------------------

def _persona_dropdown_choices() -> list[tuple[str, str]]:
    """Return (label, value) pairs for persona dropdown."""
    if persona_mgr is None:
        return []
    items = persona_mgr.list_personas()
    choices = []
    for p in items:
        count = p["message_count"]
        label = "{} ({}条)".format(p["display_name"], count)
        choices.append((label, p["id"]))
    return choices


def _persona_header_html(persona) -> str:
    """Render persona info bar above the chatbot."""
    if persona is None:
        return '<span style="opacity:.4;font-size:.85em">选择或创建一个人格开始聊天</span>'
    from src.engine.persona import RELATIONSHIP_TYPES
    rel = RELATIONSHIP_TYPES.get(persona.relationship, "")
    name_part = persona.name or ""
    bg_part = " — {}".format(persona.background[:40]) if persona.background else ""
    if persona.relationship == "self":
        return '<span style="font-size:.9em;color:#10b981"><b>本人对话</b> — 学习模式，对话内容会被用于优化模型</span>'
    return '<span style="font-size:.9em"><b>{}</b> {}{}</span>'.format(
        rel, name_part, bg_part,
    )


def create_persona(rel_type: str, name: str, background: str):
    """Create a new persona and return updated UI state."""
    if persona_mgr is None:
        gr.Warning("系统未初始化")
        return [], "", gr.update(), ""
    from src.engine.persona import RELATIONSHIP_TYPES
    label = RELATIONSHIP_TYPES.get(rel_type, "")
    p = persona_mgr.create(
        name=name.strip(),
        relationship=rel_type,
        label=label,
        background=background.strip(),
    )
    gr.Info("已创建人格：{}".format(p.display_name()))
    return (
        [],
        p.id,
        gr.update(choices=_persona_dropdown_choices(), value=p.id),
        _persona_header_html(p),
    )


def load_persona_by_id(persona_id_str: str):
    """Load a persona's chat history into the chatbot."""
    pid = persona_id_str.strip() if persona_id_str else ""
    if persona_mgr is None or not pid:
        return [], "", _persona_header_html(None)
    p = persona_mgr.load(pid)
    if p is None:
        gr.Warning("人格不存在")
        return [], "", _persona_header_html(None)
    chatbot_msgs = [{"role": m["role"], "content": m["content"]} for m in p.messages]
    return chatbot_msgs, p.id, _persona_header_html(p)


def delete_current_persona(persona_id: str):
    """Delete persona and reset chat."""
    if persona_mgr and persona_id:
        persona_mgr.delete(persona_id)
        gr.Info("人格已删除")
    return (
        [],
        "",
        gr.update(choices=_persona_dropdown_choices(), value=None),
        _persona_header_html(None),
    )


def respond(message: str, chat_history: list[dict], persona_id: str):
    """Main chat callback — responds using persona context, persists to persona."""
    if not message or not message.strip():
        return "", chat_history, persona_id

    if components is None:
        chat_history = chat_history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "系统未初始化：" + str(init_error)},
        ]
        return "", chat_history, persona_id

    tl = components.get("task_library")
    if tl and tl.get_completed_count() < MIN_CALIBRATION_TASKS:
        done = tl.get_completed_count()
        remaining = MIN_CALIBRATION_TASKS - done
        chat_history = chat_history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": (
                "请先去「校准」完成认知评估任务（还差 {} 道），"
                "当前进度：{}/{}".format(remaining, done, MIN_CALIBRATION_TASKS)
            )},
        ]
        return "", chat_history, persona_id

    persona = None
    if persona_mgr and persona_id:
        persona = persona_mgr.load(persona_id)
    if persona is None and persona_mgr:
        ensure_couple_personas()
        persona = persona_mgr.load(PARTNER_PERSONA_SELF_ID)
        persona_id = PARTNER_PERSONA_SELF_ID

    from src.data.partner_config import load_partner_wxid
    partner_wxid = load_partner_wxid().strip()

    ctx = persona.to_contact_context() if persona else None
    wxid_for_retrieval = None
    if persona and persona.relationship == "partner" and partner_wxid:
        wxid_for_retrieval = partner_wxid
        if contact_registry:
            reg = contact_registry.get_contact_context(partner_wxid)
            ctx = ctx or {}
            ctx["display_name"] = reg.get("display_name") or ctx.get("display_name", "对方")
            ctx["relationship"] = "partner"
            ctx["relationship_label"] = reg.get("relationship_label") or "伴侣/对象"
            ctx["chat_style"] = reg.get("chat_style") or {}

    history_for_llm = [{"role": h["role"], "content": h["content"]} for h in chat_history]
    reply = components["chat_engine"].chat(
        message, history_for_llm,
        contact_wxid=wxid_for_retrieval,
        contact_context=ctx,
    )

    chat_history = chat_history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]

    if persona:
        persona.add_message("user", message)
        persona.add_message("assistant", reply)
        persona_mgr.save(persona)

        is_self_mode = persona.relationship == "self"

        if is_self_mode:
            try:
                context_lines = []
                for h in chat_history:
                    role = h.get("role", "")
                    content = h.get("content", "")
                    if role == "user":
                        context_lines.append("我: {}".format(content))
                    elif role == "assistant":
                        context_lines.append("对方: {}".format(content))
                conv_text = "\n".join(context_lines[-20:])
                components["learning_loop"].learn_from_conversation(
                    conv_text,
                    conversation_id="persona_" + persona.id,
                )
                mb = components.get("memory_bank")
                if mb and len(conv_text) >= 30:
                    _api_live = components["config"].get("api", {})
                    mb.extract_from_text(
                        conv_text, components["chat_engine"].client,
                        _api_live.get("model", "gpt-4o"),
                        source="live_chat",
                    )
                    mb.save()
            except Exception as e:
                logger.warning("学习失败: %s", e)

            ap = components.get("active_probe")
            bg = components.get("belief_graph")
            if ap and bg:
                turn_count = len(chat_history) // 2
                if ap.should_probe(turn_count):
                    try:
                        beliefs = bg.query_all()[:20]
                        probe_result = ap.detect_and_probe(history_for_llm, beliefs)
                        probe_msg = ap.format_probe_as_message(probe_result)
                        if probe_msg:
                            reply = reply + " " + probe_msg
                            chat_history[-1] = {"role": "assistant", "content": reply}
                            persona.messages[-1]["content"] = reply
                            persona_mgr.save(persona)
                    except Exception as e:
                        logger.warning("主动探测失败: %s", e)

    return "", chat_history, persona_id


# ---------------------------------------------------------------------------
# Callback: Decrypt pipeline
# ---------------------------------------------------------------------------

def run_decrypt_pipeline():
    from src.data.decrypt import WeChatDecryptor
    output_dir = "data/raw"
    if components:
        output_dir = components["config"]["paths"].get("raw_db_dir", "data/raw")
    dec = WeChatDecryptor(output_dir=output_dir)
    steps = []
    for step in dec.run_full_pipeline():
        steps.append(step)
        yield _step_html(steps)
        if not step.ok:
            return


def _detect_pipeline_status() -> dict:
    """Detect what's already done: repo, compiler, keys, decrypted DBs, training."""
    repo_abs = Path("vendor/wechat-decrypt").resolve()
    keys_file = repo_abs / "all_keys.json"
    scanner = repo_abs / "find_all_keys_macos"
    output_dir = "data/raw"
    if components:
        output_dir = components["config"]["paths"].get("raw_db_dir", "data/raw")

    has_repo = (repo_abs / "decrypt_db.py").exists()
    has_scanner = scanner.exists()
    has_keys = False
    key_count = 0
    if keys_file.exists():
        try:
            with open(keys_file) as f:
                kdata = json.load(f)
            key_count = len(kdata) if isinstance(kdata, dict) else 0
            has_keys = key_count > 0
        except Exception:
            pass

    output_path = Path(output_dir)
    decrypted_dbs = list(output_path.rglob("*.db")) if output_path.exists() else []
    has_decrypted = len(decrypted_dbs) > 0

    has_training = False
    if components:
        try:
            has_training = components["vector_store"].count() > 0
        except Exception:
            pass

    from src.data.partner_config import load_partner_wxid
    has_partner = bool(load_partner_wxid().strip())

    return {
        "has_repo": has_repo,
        "has_scanner": has_scanner,
        "has_keys": has_keys,
        "key_count": key_count,
        "has_decrypted": has_decrypted,
        "db_count": len(decrypted_dbs),
        "has_training": has_training,
        "output_dir": output_dir,
        "has_partner": has_partner,
    }


def _wizard_status_html(status: dict) -> str:
    """Render the wizard status panel showing what's done and what's next."""
    def _row(label: str, done: bool, info: str = "") -> str:
        icon = "✅" if done else "⬜"
        extra = " — <small style='opacity:.7'>{}</small>".format(info) if info else ""
        return "<div style='padding:4px 0'>{} {}{}</div>".format(icon, label, extra)

    html = "<div style='background:var(--block-background-fill,#f7f7f8);border-radius:10px;padding:16px 20px;margin-bottom:12px'>"
    html += "<div style='font-weight:600;margin-bottom:8px'>当前进度</div>"
    html += _row("解密工具", status["has_repo"],
                 "已编译" if status["has_scanner"] else ("已克隆" if status["has_repo"] else ""))
    html += _row("密钥提取", status["has_keys"],
                 "{} 个密钥".format(status["key_count"]) if status["has_keys"] else "")
    html += _row("数据库解密", status["has_decrypted"],
                 "{} 个数据库".format(status["db_count"]) if status["has_decrypted"] else "")
    html += _row("对象已确认", status.get("has_partner", False),
                 "仅使用该对象的聊天记录" if status.get("has_partner") else "请在「选择 TA」中选择对象")
    from src.data.partner_config import load_twin_mode as _ltm
    _tm = _ltm()
    html += _row("训练模式", True, "训练{}的分身".format("自己" if _tm == "self" else "对象"))
    html += _row("学习完成", status["has_training"])

    calib_done = 0
    if components and components.get("task_library"):
        calib_done = components["task_library"].get_completed_count()
    html += _row("人格校准", calib_done > 0,
                 f"已完成 {calib_done} 题" if calib_done > 0 else "可选，做得越多分身越准")

    if status["has_training"]:
        html += "<div style='margin-top:10px;color:#65a88a;font-weight:600'>学习完成，可以去「心译对话」开始了</div>"
    html += "</div>"
    return html


STEP1_GUIDE_HTML = """
<div style="background:var(--block-background-fill,#f7f7f8);border-radius:10px;padding:20px;margin:8px 0">
<div style="font-weight:600;font-size:1.1em;margin-bottom:12px">准备读取聊天记录</div>
<p style="margin:0 0 8px">自动准备解密工具，让心译能读懂你的微信聊天数据。</p>
</div>
"""

def _build_step2_guide_html(repo_dir: str) -> str:
    import platform as _plat
    _sys = _plat.system()

    _card = (
        "<div style='background:var(--block-background-fill,#f7f7f8);"
        "border-radius:10px;padding:20px;margin:8px 0'>"
    )
    _code = (
        "<div style='background:#1e1e2e;color:#cdd6f4;border-radius:8px;"
        "padding:14px 16px;font-family:monospace;font-size:.9em;margin:10px 0;user-select:all'>"
    )
    _hint = "<p style='margin:8px 0 0;font-size:.85em;opacity:.7'>"

    if _sys == "Windows":
        return (
            f"{_card}"
            "<div style='font-weight:600;font-size:1.1em;margin-bottom:12px'>获取访问权限</div>"
            "<p style='margin:0 0 10px'>读取微信进程内存需要管理员权限。<br>"
            "心译本身就是从终端启动的，<b>只需用管理员终端启动心译</b>，密钥提取会自动完成，不需要另开窗口。</p>"
            "<div style='background:#2a2225;border-radius:8px;padding:14px 16px;margin:0 0 12px'>"
            "<div style='font-size:.85em;color:#a8969a;margin-bottom:8px;font-weight:600'>如何以管理员方式启动心译</div>"
            "<ol style='margin:0;padding-left:18px;line-height:2;color:#d4c4c8;font-size:.9em'>"
            "<li>按 <kbd style='background:#3a3035;padding:1px 6px;border-radius:4px'>Win+X</kbd>，选「Windows PowerShell（管理员）」或「终端（管理员）」</li>"
            "<li>在管理员终端里切到项目目录，运行 <code>python src/app.py</code></li>"
            "<li>确保微信已打开并登录</li>"
            "<li>回到这里，点下方「提取密钥」按钮</li>"
            "</ol>"
            "</div>"
            f"{_hint}标题栏显示「管理员」说明权限正确；点「提取密钥」后稍等片刻，看到绿色提示即成功。</p>"
            "<details style='margin-top:12px;font-size:.85em'>"
            "<summary style='cursor:pointer;opacity:.7'>⚠️ 如果提示 Access Denied 或找不到进程</summary>"
            "<ul style='margin:4px 0 0;padding-left:20px;opacity:.8;line-height:1.8'>"
            "<li>确认 PowerShell 标题栏有「管理员」字样</li>"
            "<li>微信（Weixin.exe）正在运行且已登录</li>"
            "<li>若杀毒软件拦截了 Python，临时关闭或加白名单</li>"
            "</ul>"
            "</details>"
            "</div>"
        )
    elif _sys == "Linux":
        return (
            f"{_card}"
            "<div style='font-weight:600;font-size:1.1em;margin-bottom:12px'>获取访问权限</div>"
            "<p style='margin:0 0 8px'>Linux 需要 root 权限或 <code>CAP_SYS_PTRACE</code> 来读取微信进程内存。</p>"
            f"{_code}cd {repo_dir} && sudo python3 find_all_keys.py</div>"
            f"{_hint}看到 <code>Saved to all_keys.json</code> 就说明成功了，回来点下面的「检测密钥」按钮。</p>"
            "<details style='margin-top:12px;font-size:.85em'>"
            "<summary style='cursor:pointer;opacity:.7'>⚠️ 如果提示 Permission denied</summary>"
            "<p style='margin:8px 0 4px'>可以改用 ptrace capability 而不必全程 sudo：</p>"
            "<div style='background:#1e1e2e;color:#cdd6f4;border-radius:6px;padding:10px 14px;"
            "font-family:monospace;font-size:.85em;margin:4px 0'>"
            "sudo setcap cap_sys_ptrace+eip $(which python3)</div>"
            "</details>"
            "</div>"
        )
    else:  # macOS
        return (
            f"{_card}"
            "<div style='font-weight:600;font-size:1.1em;margin-bottom:12px'>获取访问权限</div>"
            "<p style='margin:0 0 8px'>macOS 安全机制限制，需要你在<b>终端</b>里手动运行一行命令来获取聊天数据的访问权限。</p>"
            f"{_code}cd {repo_dir} && sudo ./find_all_keys_macos</div>"
            f"{_hint}打开「终端」App → 粘贴上面的命令 → 输入电脑密码 → 等待扫描完成。<br>"
            "看到 <code>Saved to all_keys.json</code> 就说明成功了，回来点下面的「检测密钥」按钮。</p>"
            "<details style='margin-top:12px;font-size:.85em'>"
            "<summary style='cursor:pointer;opacity:.7'>⚠️ 如果提示 task_for_pid failed（首次需要）</summary>"
            "<p style='margin:8px 0 4px'>需要临时关闭 SIP 调试限制（一次性操作）：</p>"
            "<ol style='margin:0;padding-left:20px;opacity:.8'>"
            "<li>关机 → 按住电源键直到看到「选项」→ 点「选项」进入恢复模式</li>"
            "<li>顶部菜单「实用工具」→「终端」，输入：<code>csrutil enable --without debug</code></li>"
            "<li>重启回来，重新运行上面的命令</li>"
            "<li>用完后可以恢复：再次进恢复模式输入 <code>csrutil enable</code></li>"
            "</ol>"
            "</details>"
            "</div>"
        )

STEP2_GUIDE_HTML = "{repo_dir}"  # placeholder, replaced at render time via _build_step2_guide_html

STEP3_GUIDE_HTML = """
<div style="background:var(--block-background-fill,#f7f7f8);border-radius:10px;padding:20px;margin:8px 0">
<div style="font-weight:600;font-size:1.1em;margin-bottom:12px">开始学习 TA 的说话方式</div>
<p style="margin:0">请先选择对象。准备就绪后，点击下方按钮：读取聊天记录 → 学习 TA 的语气 → 构建记忆</p>
</div>
"""


def check_status():
    """Refresh and return wizard status HTML."""
    status = _detect_pipeline_status()
    return _wizard_status_html(status)


def _step1_pipeline(runner):
    """Step 1 pipeline: clone repo + install deps + compile scanner. Runs in background."""
    global contact_registry
    from src.data.decrypt import WeChatDecryptor, DecryptStep as DS
    output_dir = "data/raw"
    if components:
        output_dir = components["config"]["paths"].get("raw_db_dir", "data/raw")
    dec = WeChatDecryptor(output_dir=output_dir)

    runner.add(DS("克隆仓库", True, "正在下载解密工具…"))
    step = _timed(runner, lambda: dec.clone_repo(),
                  lambda e: DS("克隆仓库", True, "下载中… 已等待 {}s".format(e)))
    runner.update(step)
    if not step.ok:
        return

    runner.add(DS("安装依赖", True, "正在安装…"))
    step = _timed(runner, lambda: dec.install_deps(),
                  lambda e: DS("安装依赖", True, "安装中… 已等待 {}s".format(e)))
    runner.update(step)

    runner.add(DS("编译扫描器", True, "正在编译…"))
    step = _timed(runner, lambda: dec.compile_macos_scanner(),
                  lambda e: DS("编译扫描器", True, "编译中… 已等待 {}s".format(e)))
    runner.update(step)
    if not step.ok:
        return

    runner.add(DS("准备完成", True, "解密工具已就绪，请进行第 2 步"))


def run_step1_prepare():
    """Step 1: clone repo + install deps + compile scanner. Returns (html, timer_update)."""
    runner = TrainingRunner.instance()
    if runner.is_running():
        return _step_html(runner.get_steps()), gr.Timer(active=True)
    runner.start(_step1_pipeline, render_fn=_step_html, mode="step1")
    return '<div class="step-card step-ok">⏳ 正在准备解密工具…</div>', gr.Timer(active=True)


def _keys_has_main_message_db(keys: dict) -> bool:
    """True if all_keys.json contains a key for message/message_N.db (private chat DBs)."""
    import re as _re
    pat = _re.compile(r"^message[/\\]message_\d+\.db$")
    for k in keys:
        if pat.match(k.replace("\\", "/")):
            return True
    return False


def run_step2_reextract_instructions():
    """Show why re-extraction may be needed + platform-specific commands."""
    import platform as _plat

    repo_dir = Path("vendor/wechat-decrypt").resolve()
    _sys = _plat.system()
    bug = (
        "<div style='background:rgba(245,158,11,.12);border-radius:8px;padding:12px 14px;margin:0 0 14px;"
        "border-left:3px solid #d97706;font-size:.92em;line-height:1.75'>"
        "<b>常见问题：</b>私聊消息在 <code>message/message_0.db</code>、<code>message_1.db</code> … "
        "若提取时微信未在运行、或扫描不完整，这些库<strong>没有对应密钥</strong>，解密会跳过，"
        "「选择 TA」扫描联系人可能为 <b>0</b>。请<strong>保持微信已登录并运行</strong>后，在终端重新执行下方命令，"
        "再点「重新检测密钥」，最后在第 3 步重新解密。"
        "</div>"
    )
    _code = (
        "<div style='background:#1e1e2e;color:#cdd6f4;border-radius:8px;"
        "padding:14px 16px;font-family:monospace;font-size:.88em;margin:10px 0;user-select:all;white-space:pre-wrap'>"
    )
    if _sys == "Windows":
        cmd = "cd /d {}\npython find_all_keys_windows.py".format(str(repo_dir))
        extra = (
            "<p style='margin:10px 0 0;font-size:.85em;opacity:.8'>"
            "请用<b>管理员</b>终端运行（与启动心译同一方式）。看到 <code>Saved to all_keys.json</code> 后回到此处。"
            "</p>"
        )
    elif _sys == "Linux":
        cmd = "cd {} && sudo python3 find_all_keys.py".format(str(repo_dir))
        extra = (
            "<p style='margin:10px 0 0;font-size:.85em;opacity:.8'>"
            "看到 <code>Saved to all_keys.json</code> 后回到此处。"
            "</p>"
        )
    else:
        cmd = "cd {} && sudo ./find_all_keys_macos".format(str(repo_dir))
        extra = (
            "<p style='margin:10px 0 0;font-size:.85em;opacity:.8'>"
            "若 C 版不存在，可试：<code>sudo python3 find_all_keys.py</code>（部分 macOS 版本会提示不支持，请以仓库说明为准）。"
            "看到 <code>Saved to all_keys.json</code> 后回到此处。"
            "</p>"
        )
    return (
        bug
        + "<div style='font-weight:600;margin-bottom:6px'>请在本机终端执行：</div>"
        + _code
        + cmd
        + "</div>"
        + extra
    )


def run_step2_check_keys():
    """Step 2: detect if keys file exists after user runs the command manually."""
    keys_file = Path("vendor/wechat-decrypt/all_keys.json").resolve()
    if not keys_file.exists():
        return (
            '<div class="step-card step-fail">'
            "✗ 未检测到密钥文件<br>"
            "<small style='opacity:.7'>请先在终端运行密钥提取命令，看到 'Saved to all_keys.json' 后再点此按钮</small>"
            "</div>"
        )
    try:
        with open(keys_file) as f:
            kdata = json.load(f)
        count = len(kdata) if isinstance(kdata, dict) else 0
        if count == 0:
            return '<div class="step-card step-fail">✗ 密钥文件为空，请重新提取</div>'
        ok_block = (
            '<div class="step-card step-ok">'
            "✓ 检测到 {} 个密钥条目，可以进行第 3 步了"
            "</div>"
        ).format(count)
        if isinstance(kdata, dict) and not _keys_has_main_message_db(kdata):
            ok_block += (
                "<div class='step-card step-fail' style='margin-top:10px'>"
                "⚠️ <b>未检测到主消息库密钥</b>（<code>message/message_0.db</code> 等）。"
                "私聊可能无法解密，扫描联系人容易为 0。请点「重新提取密钥」按说明在终端重跑提取（微信保持运行），"
                "再点「重新检测密钥」，并重新执行第 3 步解密。"
                "</div>"
            )
        return ok_block
    except Exception as e:
        return '<div class="step-card step-fail">✗ 密钥文件读取失败: {}</div>'.format(e)


def _decrypt_only_pipeline(runner):
    """Decrypt databases only (no training). Runs in a background thread."""
    from src.data.decrypt import WeChatDecryptor, DecryptStep as DS

    c = components
    config = c["config"]
    output_dir = config["paths"].get("raw_db_dir", "data/raw")
    dec = WeChatDecryptor(output_dir=output_dir)

    keys_file = Path("vendor/wechat-decrypt/all_keys.json").resolve()
    if not keys_file.exists():
        runner.add(DS("检查密钥", False, "未找到密钥文件，请先完成第 2 步"))
        return
    try:
        with open(keys_file) as f:
            kdata = json.load(f)
        count = len(kdata) if isinstance(kdata, dict) else 0
        runner.add(DS("检查密钥", True, "{} 个密钥".format(count)))
    except Exception as e:
        runner.add(DS("检查密钥", False, str(e)))
        return

    runner.add(DS("数据库解密", True, "正在解密…"))
    try:
        step = _timed(runner, lambda: dec.decrypt_databases(),
                      lambda e: DS("数据库解密", True, "解密中… 已等待 {}s".format(e)))
        runner.update(step)
        if not step.ok:
            return
    except Exception as e:
        runner.update(DS("数据库解密", False, str(e)))
        return

    c["parser"].set_db_dir(output_dir)
    runner.add(DS("完成", True, "数据库解密成功，请前往「选择 TA」扫描联系人"))


def run_step3_decrypt_only():
    """Step 3: decrypt DBs only (no training). Returns (html, timer_update)."""
    if components is None:
        from src.data.decrypt import DecryptStep as DS
        return _step_html([DS("系统检查", False, "系统未初始化：" + str(init_error))]), gr.Timer(active=False)
    runner = TrainingRunner.instance()
    if runner.is_running():
        return _step_html(runner.get_steps()), gr.Timer(active=True)
    runner.start(_decrypt_only_pipeline, render_fn=_step_html, mode="step3")
    return '<div class="step-card step-ok">⏳ 解密启动中…</div>', gr.Timer(active=True)


def _step3_pipeline(runner):
    """Step 3 pipeline: decrypt DBs + full training. Runs in a background thread."""
    global contact_registry
    from src.data.decrypt import WeChatDecryptor, DecryptStep as DS
    from src.personality.prompt_builder import PromptBuilder

    c = components
    config = c["config"]
    output_dir = config["paths"].get("raw_db_dir", "data/raw")
    dec = WeChatDecryptor(output_dir=output_dir)

    keys_file = Path("vendor/wechat-decrypt/all_keys.json").resolve()
    if not keys_file.exists():
        runner.add(DS("检查密钥", False, "未找到密钥文件，请先完成第 2 步"))
        return
    try:
        with open(keys_file) as f:
            kdata = json.load(f)
        count = len(kdata) if isinstance(kdata, dict) else 0
        runner.add(DS("检查密钥", True, "{} 个密钥".format(count)))
    except Exception as e:
        runner.add(DS("检查密钥", False, str(e)))
        return

    runner.add(DS("数据库解密", True, "正在解密…"))
    try:
        step = _timed(runner, lambda: dec.decrypt_databases(),
                      lambda e: DS("数据库解密", True, "解密中… 已等待 {}s".format(e)))
        runner.update(step)
        if not step.ok:
            return
    except Exception as e:
        runner.update(DS("数据库解密", False, str(e)))
        return

    c["parser"].set_db_dir(output_dir)

    runner.add(DS("读取消息", True, "正在读取微信数据库…"))
    messages = c["parser"].get_all_text_messages()
    if not messages:
        runner.update(DS("读取消息", False, "未找到消息，解密可能未生成有效数据库"))
        return
    runner.update(DS("读取消息", True, "{:,} 条文本消息".format(len(messages))))

    from src.data.partner_config import load_partner_wxid, load_twin_mode
    pw = load_partner_wxid().strip()
    if not pw:
        runner.update(DS("确认对象", False, "请先在「选择 TA」中扫描并保存对象"))
        return
    twin_mode = load_twin_mode()
    twin_label = "自己" if twin_mode == "self" else "对象"
    runner.add(DS("训练模式", True, "训练 **{}** 的分身".format(twin_label)))

    cleaned_all = c["cleaner"].clean_messages(messages)
    cs = c["cleaner"].last_stats
    cleaned = [m for m in cleaned_all if m.get("StrTalker") == pw]
    if len(cleaned) < PARTNER_MIN_TRAIN_MESSAGES:
        runner.update(DS(
            "对象会话",
            False,
            "与对象的清洗后消息仅 {:,} 条（至少需要 {} 条），请确认选对人或先多聊一些".format(
                len(cleaned), PARTNER_MIN_TRAIN_MESSAGES,
            ),
        ))
        return
    clean_detail = "全库清洗 {:,} 条 → **仅对象** {:,} 条（过滤 {:,} 条非对象）".format(
        len(cleaned_all), len(cleaned), len(cleaned_all) - len(cleaned),
    )
    if cs:
        parts = []
        if cs.dropped_binary:
            parts.append("二进制{}".format(cs.dropped_binary))
        if cs.dropped_system:
            parts.append("系统消息{}".format(cs.dropped_system))
        if cs.dropped_pure_emoji:
            parts.append("纯表情{}".format(cs.dropped_pure_emoji))
        if cs.dropped_pure_url:
            parts.append("纯链接{}".format(cs.dropped_pure_url))
        if cs.dropped_too_short:
            parts.append("过短{}".format(cs.dropped_too_short))
        if cs.stripped_wxid_prefix:
            parts.append("群聊wxid前缀清除{}".format(cs.stripped_wxid_prefix))
        if cs.redacted_pii:
            parts.append("PII脱敏{}".format(cs.redacted_pii))
        if parts:
            clean_detail += "（" + "、".join(parts) + "）"
    runner.add(DS("数据清洗", True, clean_detail))

    c["builder"].twin_mode = twin_mode
    conversations = c["builder"].build_conversations(cleaned)
    for conv in conversations:
        conv["turn_count"] = len(conv.get("turns", []))
    runner.add(DS("构建对话段", True, "{:,} 段对话（{} 侧为主角）".format(len(conversations), twin_label)))

    # --- checkpoint detection ---
    db_mt = _get_db_mtime(config)
    skipped = 0

    # --- 人格分析 ---
    persona_path = Path(config["paths"]["persona_file"])
    _needs_regen = not _ckpt_valid(persona_path, db_mt)
    if not _needs_regen:
        profile = yaml.safe_load(open(persona_path, encoding="utf-8"))
        if not profile.get("vocab_bank"):
            _needs_regen = True
    if not _needs_regen:
        runner.add(DS("人格分析", True, "已有数据，跳过 ⏩"))
        skipped += 1
    else:
        runner.add(DS("人格分析", True, "正在分析人格特征（{} 侧）…".format(twin_label)))
        profile = _timed(runner, lambda: c["analyzer"].analyze(cleaned, twin_mode=twin_mode),
                         lambda e: DS("人格分析", True, "分析中… 已等待 {}s".format(e)))
        persona_path.parent.mkdir(parents=True, exist_ok=True)
        with open(persona_path, "w", encoding="utf-8") as f:
            yaml.dump(profile, f, allow_unicode=True)
        runner.update(DS("人格分析", True, "人格画像已生成并保存（含词库）"))

    # --- 情绪训练 ---
    from src.personality.emotion_analyzer import EmotionAnalyzer as _EA
    from src.personality.emotion_tracker import EmotionTracker as _ET
    emo_path = Path(config["paths"].get("emotion_file", "data/emotion_profile.yaml"))
    if _ckpt_valid(emo_path, db_mt):
        emo_profile = yaml.safe_load(open(emo_path, encoding="utf-8"))
        runner.add(DS("情绪训练", True, "已有数据，跳过 ⏩"))
        skipped += 1
    else:
        runner.add(DS("情绪训练", True, "正在训练情绪模型（{} 侧）…".format(twin_label)))
        emo_analyzer = _EA()
        emo_profile = _timed(runner, lambda: emo_analyzer.train(cleaned, twin_mode=twin_mode),
                             lambda e: DS("情绪训练", True, "训练中… 已等待 {}s".format(e)))
        emo_analyzer.save(str(emo_path))
        emo_dist = emo_profile.get("emotion_distribution", {})
        emo_sorted = sorted(emo_dist.items(), key=lambda x: -x[1])
        emo_summary = ", ".join("{}:{}".format(k, v) for k, v in emo_sorted)
        runner.update(DS("情绪训练", True, "已分析 {:,} 条消息，{}种情绪 ({})".format(emo_profile.get("total_analyzed", 0), len(emo_sorted), emo_summary)))
    _api_cfg = config.get("api", {})
    from openai import OpenAI as _OAI_emo
    _emo_cl = _OAI_emo(
        api_key=_api_cfg.get("api_key", ""),
        base_url=_api_cfg.get("base_url"),
        default_headers=_api_cfg.get("headers", {}),
    )
    c["emotion_tracker"] = _ET(emo_profile, api_client=_emo_cl, model=_api_cfg.get("model", "gpt-4o"))

    # --- 思维训练 ---
    think_path = Path(config["paths"].get("thinking_model_file", "data/thinking_model.txt"))
    if _ckpt_valid(think_path, db_mt):
        _thinking = think_path.read_text(encoding="utf-8")
        runner.add(DS("思维训练", True, "已有数据（{} 字），跳过 ⏩".format(len(_thinking))))
        skipped += 1
    else:
        runner.add(DS("思维训练", True, "正在从对话数据中提取思维模式（约 3-5 分钟）…"))
        try:
            from src.personality.thinking_profiler import ThinkingProfiler as _TP
            api_cfg = config.get("api", {})
            from openai import OpenAI as _OAI
            _tp_client = _OAI(
                api_key=api_cfg.get("api_key", ""),
                base_url=api_cfg.get("base_url"),
                default_headers=api_cfg.get("headers", {}),
            )
            tp = _TP(_tp_client, api_cfg.get("model", "gpt-4o"))
            _thinking = _retry_api(
                lambda: _timed(runner, lambda: tp.train(conversations),
                               lambda e: DS("思维训练", True, "正在训练… 已等待 {}s".format(e))),
                runner, "⚠ 思维训练",
            )
            _thinking = _thinking or ""
            tp.save(_thinking, str(think_path))
            runner.update(DS("思维训练", True, "数据驱动思维模型已生成（{} 字）".format(len(_thinking))))
        except Exception as e:
            logger.warning("Thinking profiler training failed: %s", e)
            _thinking = ""
            runner.update(DS("思维训练", False, "思维训练失败: {}".format(e)))

    # --- 认知参数提取 ---
    _cog_profile = {}
    try:
        from src.personality.thinking_profiler import ThinkingProfiler as _TP_cog
        _cog_path = Path("data/cognitive_profile.json")
        _s1_api = config.get("api", {})
        if not _cog_path.exists() or (_cog_path.exists() and db_mt > _cog_path.stat().st_mtime):
            runner.update(DS("认知参数", False, "提取认知风格参数…"))
            from openai import OpenAI as _OAI_cog
            _cog_client = _OAI_cog(
                api_key=_s1_api.get("api_key", ""),
                base_url=_s1_api.get("base_url"),
                default_headers=_s1_api.get("headers", {}),
            )
            _tp_cog = _TP_cog(_cog_client, _s1_api.get("model", "gpt-4o"))
            _cog_profile = _retry_api(
                lambda: _tp_cog.extract_cognitive_profile(conversations),
                runner, "⚠ 认知参数",
            )
            if _cog_profile:
                _TP_cog.save_cognitive_profile(_cog_profile)
                runner.update(DS("认知参数", True, "认知参数已提取"))
            else:
                runner.update(DS("认知参数", False, "数据不足，跳过"))
        else:
            _cog_profile = _TP_cog.load_cognitive_profile()
            runner.update(DS("认知参数", True, "已有认知参数，跳过"))
    except Exception as e:
        logger.warning("Cognitive profile extraction failed: %s", e)
        runner.update(DS("认知参数", False, "认知参数提取失败: {}".format(e)))

    # --- 情绪边界提取 ---
    _emo_boundaries = []
    try:
        from src.personality.thinking_profiler import ThinkingProfiler as _TP_eb
        _eb_path = Path("data/emotion_boundaries.json")
        _s1_api_eb = config.get("api", {})
        if not _eb_path.exists() or (_eb_path.exists() and db_mt > _eb_path.stat().st_mtime):
            runner.add(DS("情绪边界", False, "提取情绪反应边界…"))
            from openai import OpenAI as _OAI_eb
            _eb_client = _OAI_eb(
                api_key=_s1_api_eb.get("api_key", ""),
                base_url=_s1_api_eb.get("base_url"),
                default_headers=_s1_api_eb.get("headers", {}),
            )
            _tp_eb = _TP_eb(_eb_client, _s1_api_eb.get("model", "gpt-4o"))
            import src.app as _self_mod
            _cr = getattr(_self_mod, 'contact_registry', None)
            _emo_boundaries = _retry_api(
                lambda: _tp_eb.extract_emotion_boundaries(conversations, contact_registry=_cr),
                runner, "⚠ 情绪边界",
            )
            if _emo_boundaries:
                _TP_eb.save_emotion_boundaries(_emo_boundaries)
                _n_eb = sum(len(v) for v in _emo_boundaries.values()) if isinstance(_emo_boundaries, dict) else len(_emo_boundaries)
                _rel_types = list(_emo_boundaries.keys()) if isinstance(_emo_boundaries, dict) else ["default"]
                runner.update(DS("情绪边界", True, "已提取 {} 条（关系类型: {}）".format(_n_eb, ", ".join(_rel_types))))
            else:
                runner.update(DS("情绪边界", False, "数据不足，跳过"))
        else:
            _emo_boundaries = _TP_eb.load_emotion_boundaries()
            _n_cached = sum(len(v) for v in _emo_boundaries.values()) if isinstance(_emo_boundaries, dict) else len(_emo_boundaries)
            runner.add(DS("情绪边界", True, "已有情绪边界（{} 条），跳过".format(_n_cached)))
            skipped += 1
    except Exception as e:
        logger.warning("Emotion boundary extraction failed: %s", e)
        runner.update(DS("情绪边界", False, "情绪边界提取失败: {}".format(e)))

    # --- 情绪表达风格提取 ---
    _emo_expression = {}
    try:
        from src.personality.thinking_profiler import ThinkingProfiler as _TP_expr
        _expr_path = Path("data/emotion_expression.json")
        _s1_api_expr = config.get("api", {})
        if not _expr_path.exists() or (_expr_path.exists() and db_mt > _expr_path.stat().st_mtime):
            runner.add(DS("情绪表达", False, "提取情绪表达风格…"))
            from openai import OpenAI as _OAI_expr
            _expr_client = _OAI_expr(
                api_key=_s1_api_expr.get("api_key", ""),
                base_url=_s1_api_expr.get("base_url"),
                default_headers=_s1_api_expr.get("headers", {}),
            )
            _tp_expr = _TP_expr(_expr_client, _s1_api_expr.get("model", "gpt-4o"))
            _emo_expression = _retry_api(
                lambda: _tp_expr.extract_emotion_expression_style(conversations),
                runner, "⚠ 情绪表达",
            )
            if _emo_expression:
                _TP_expr.save_emotion_expression(_emo_expression)
                runner.update(DS("情绪表达", True, "已提取 {} 种情绪表达方式".format(len(_emo_expression))))
            else:
                runner.update(DS("情绪表达", False, "数据不足，跳过"))
        else:
            _emo_expression = _TP_expr.load_emotion_expression()
            runner.add(DS("情绪表达", True, "已有情绪表达风格（{} 种），跳过".format(len(_emo_expression))))
            skipped += 1
    except Exception as e:
        logger.warning("Emotion expression extraction failed: %s", e)
        runner.update(DS("情绪表达", False, "情绪表达提取失败: {}".format(e)))

    c["prompt_builder"] = PromptBuilder(
        persona_profile=profile,
        cold_start_description=config.get("cold_start_description", ""),
        thinking_model=_thinking,
        cognitive_profile=_cog_profile,
        emotion_boundaries=_emo_boundaries,
        emotion_expression=_emo_expression,
    )
    c["prompt_builder"].regenerate_guidance()
    runner.update(DS("指引文件", True, "已生成 identity/thinking/emotion/style/rules.md"))
    c["chat_engine"].set_components(
        c["retriever"], c["belief_graph"], c["prompt_builder"],
        c["vector_store"], c["emotion_tracker"],
        memory_bank=c.get("memory_bank"),
    )

    # --- 嵌入模型检测 ---
    _emb = c["embedder"]
    if _emb.is_model_cached():
        runner.add(DS("嵌入模型", True, "已就绪"))
    else:
        runner.add(DS("嵌入模型", True, "首次使用，正在下载嵌入模型（约 1-2GB）…"))
        try:
            _timed(runner, lambda: _emb.download_model(),
                   lambda e: DS("嵌入模型", True, "下载中… 已等待 {}s".format(e)))
            runner.update(DS("嵌入模型", True, "嵌入模型下载完成"))
        except Exception as e:
            runner.update(DS("嵌入模型", False, "下载失败: {}，请检查网络连接".format(e)))
            return

    # --- 向量化 ---
    vec_count = c["vector_store"].count()
    chroma_sqlite = Path(config["paths"]["chroma_dir"]) / "chroma.sqlite3"
    if vec_count > 0 and _ckpt_valid(chroma_sqlite, db_mt, min_size=1000):
        runner.add(DS("向量化存储", True, "已有 {:,} 段，跳过 ⏩".format(vec_count)))
        skipped += 1
    else:
        runner.add(DS("向量化存储", True, "正在写入向量库…"))
        try:
            _timed(runner, lambda: c["vector_store"].add_conversations(conversations, c["embedder"]),
                   lambda e: DS("向量化存储", True, "写入中… 已等待 {}s".format(e)))
            runner.update(DS("向量化存储", True, "向量库共 {:,} 段".format(c["vector_store"].count())))
        except Exception as e:
            runner.update(DS("向量化存储", False, "向量化失败: {}".format(e)))

    # --- 信念图谱 ---
    bg = c["belief_graph"]
    beliefs_path = Path(config["paths"]["beliefs_file"])
    if bg.count() > 0 and _ckpt_valid(beliefs_path, db_mt, min_size=100):
        runner.add(DS("重建信念图谱", True, "已有 {} 条信念，跳过 ⏩".format(bg.count())))
        skipped += 1
    else:
        runner.add(DS("重建信念图谱", True, "正在从对话数据中提取信念…"))
        old_count = bg.count()
        bg.beliefs.clear()
        bg.contradictions.clear()
        bg._embeddings.clear()
        bg._next_id = 1
        bg.save()
        ll = c["learning_loop"]
        try:
            _timed(runner, lambda: ll.batch_extract_beliefs(conversations, top_n_contacts=1, samples_per_contact=20),
                   lambda e: DS("重建信念图谱", True, "提取中… 已等待 {}s（当前 {} 条）".format(e, bg.count())))
            runner.update(DS("重建信念图谱", True, "{} → {} 条信念（从对话数据提取）".format(old_count, bg.count())))
        except Exception as e:
            logger.warning("Belief extraction failed: %s", e)
            runner.update(DS("重建信念图谱", False, "信念图谱重建失败: {}".format(e)))

    # --- 记忆提取 ---
    mb = c.get("memory_bank")
    if mb is None:
        from src.memory.memory_bank import MemoryBank
        mb = MemoryBank(filepath="data/memories.json", embedder=c["embedder"])
        c["memory_bank"] = mb
    mem_path = Path("data/memories.json")
    if mb.count() > 0 and _ckpt_valid(mem_path, db_mt, min_size=10):
        high_conf = sum(1 for m in mb.memories if m.confidence >= 0.7)
        runner.add(DS("记忆提取", True, "已有 {} 条记忆（高置信 {} 条），跳过 ⏩".format(mb.count(), high_conf)))
        skipped += 1
    else:
        runner.add(DS("记忆提取", True, "正在从对话中提取事实记忆…"))
        try:
            mb.clear()
            _api_mb = config.get("api", {})
            from openai import OpenAI as _OAI_mb
            _mb_client = _OAI_mb(
                api_key=_api_mb.get("api_key", ""),
                base_url=_api_mb.get("base_url"),
                default_headers=_api_mb.get("headers", {}),
            )
            _timed(runner, lambda: mb.batch_extract(conversations, _mb_client, _api_mb.get("model", "gpt-4o")),
                   lambda e: DS("记忆提取", True, "提取中… 已等待 {}s（当前 {} 条）".format(e, mb.count())))
            high_conf = sum(1 for m in mb.memories if m.confidence >= 0.7)
            runner.update(DS("记忆提取", True, "{} 条记忆（高置信 {} 条）".format(mb.count(), high_conf)))
        except Exception as e:
            logger.warning("Memory extraction failed: %s", e)
            runner.update(DS("记忆提取", False, "记忆提取失败: {}".format(e)))

    # --- 联系人分类 ---
    contacts_path = Path("data/contacts.json")
    if _ckpt_valid(contacts_path, db_mt, min_size=10):
        runner.add(DS("联系人分类", True, "已有数据，跳过 ⏩"))
        skipped += 1
    else:
        runner.add(DS("联系人分类", True, "正在更新联系人库与对象聊天风格…"))
        try:
            if contact_registry is None:
                from src.data.contact_registry import ContactRegistry
                contact_registry = ContactRegistry()
            contacts_db = c["parser"].get_contacts()
            contact_registry.build_from_messages(messages, contacts_db)
            if pw in contact_registry.contacts:
                style = c["analyzer"].analyze_per_contact(cleaned, pw)
                if style:
                    contact_registry.set_chat_style(pw, style)
            runner.update(DS(
                "联系人分类",
                True,
                "{} 个联系人；对象「{}」聊天风格已更新".format(
                    contact_registry.count(),
                    contact_registry.get_display_name(pw),
                ),
            ))
        except Exception as e:
            logger.warning("Contact registry build failed: %s", e)
            runner.update(DS("联系人分类", False, "联系人分类失败: {}".format(e)))

    # 检查关键文件是否生成成功
    _critical_missing = []
    for _cf_label, _cf_path in [
        ("思维模型", "data/thinking_model.txt"),
        ("认知参数", "data/cognitive_profile.json"),
        ("情绪边界", "data/emotion_boundaries.json"),
        ("情绪表达", "data/emotion_expression.json"),
    ]:
        if not Path(_cf_path).exists() or Path(_cf_path).stat().st_size < 50:
            _critical_missing.append(_cf_label)

    if _critical_missing:
        runner.add(DS("训练未完成", False,
                       "以下关键步骤因 API 错误未完成：{}。请检查 API 后重新训练。".format("、".join(_critical_missing))))
        runner.error = "关键步骤失败: " + "、".join(_critical_missing)
    elif skipped:
        runner.add(DS("学习完成", True, "跳过 {} 个已完成步骤 ⏩".format(skipped)))
    else:
        runner.add(DS("学习完成", True, "所有步骤完成，请前往「校准」进一步校准"))


def run_step3_decrypt_and_train():
    """Step 3: decrypt DBs with existing keys, then run full training pipeline.

    Returns (html, timer_update): initial status + activate polling timer.
    """
    if components is None:
        from src.data.decrypt import DecryptStep as DS
        return _step_html([DS("系统检查", False, "系统未初始化：" + str(init_error))]), gr.Timer(active=False)
    from src.data.partner_config import load_partner_wxid
    if not load_partner_wxid().strip():
        from src.data.decrypt import DecryptStep as DS
        return (
            _step_html([DS("确认对象", False, "请先在「选择 TA」中扫描并保存对象。")]),
            gr.Timer(active=False),
        )
    runner = TrainingRunner.instance()
    if runner.is_running():
        return _step_html(runner.get_steps()), gr.Timer(active=True)
    runner.start(_step3_pipeline, render_fn=_step_html, mode="step3")
    return '<div class="step-card step-ok">⏳ 解密 + 训练启动中…</div>', gr.Timer(active=True)


def link_external_dir(path_str: str):
    from src.data.decrypt import WeChatDecryptor, DecryptStep
    if not path_str or not path_str.strip():
        return '<div class="step-card step-fail">✗ 请输入路径</div>', ""

    scan = WeChatDecryptor.scan_directory(path_str.strip())
    if not scan["valid"]:
        return f'<div class="step-card step-fail">✗ {scan["error"]}</div>', ""

    summary = (
        f"发现 {scan['db_count']} 个数据库文件\n"
        f"联系人库: {'✓' if scan['has_contact_db'] else '✗'}  "
        f"消息库: {'✓' if scan['has_message_db'] else '✗'}"
    )

    target = "data/raw"
    if components:
        target = components["config"]["paths"].get("raw_db_dir", "data/raw")

    result = WeChatDecryptor.link_decrypted_dir(path_str.strip(), target)

    if components:
        components["parser"].set_db_dir(target)

    html = _step_html([result])
    return html, summary


# ---------------------------------------------------------------------------
# Callback: Import data pipeline
# ---------------------------------------------------------------------------

def _import_pipeline(runner):
    """Full import + train pipeline. Runs in a background thread."""
    from src.personality.prompt_builder import PromptBuilder

    c = components
    config = c["config"]

    runner.add("⏳ 读取微信数据库…")
    messages = c["parser"].get_all_text_messages()
    if not messages:
        runner.add("⚠️ 未找到消息数据。请先在「连接」中导入解密后的数据库。")
        return
    runner.update("✓ 读取消息: {:,} 条".format(len(messages)))

    from src.data.partner_config import load_partner_wxid, load_twin_mode
    pw = load_partner_wxid().strip()
    if not pw:
        runner.update("⚠️ 请先在「选择 TA」中扫描并保存对象。")
        return
    twin_mode = load_twin_mode()
    twin_label = "自己" if twin_mode == "self" else "对象"
    runner.add("ℹ️ 训练模式：训练 **{}** 的分身".format(twin_label))

    runner.add("⏳ 数据清洗…")
    cleaned_all = c["cleaner"].clean_messages(messages)
    cleaned = [m for m in cleaned_all if m.get("StrTalker") == pw]
    if len(cleaned) < PARTNER_MIN_TRAIN_MESSAGES:
        runner.update(
            "⚠️ 与对象的清洗后消息仅 {:,} 条（至少需要 {} 条），请确认选对人。".format(
                len(cleaned), PARTNER_MIN_TRAIN_MESSAGES,
            )
        )
        return
    cs = c["cleaner"].last_stats
    runner.update(
        "✓ 清洗: 全库 {:,} 条 → **仅对象** {:,} 条（非对象 {:,} 条已排除）".format(
            len(cleaned_all), len(cleaned), len(cleaned_all) - len(cleaned),
        )
    )
    if cs:
        parts = []
        if cs.dropped_binary:
            parts.append("二进制{}".format(cs.dropped_binary))
        if cs.dropped_system:
            parts.append("系统消息{}".format(cs.dropped_system))
        if cs.dropped_pure_emoji:
            parts.append("纯表情{}".format(cs.dropped_pure_emoji))
        if cs.dropped_pure_url:
            parts.append("纯链接{}".format(cs.dropped_pure_url))
        if cs.dropped_too_short:
            parts.append("过短{}".format(cs.dropped_too_short))
        if cs.stripped_wxid_prefix:
            parts.append("群聊wxid前缀清除{}".format(cs.stripped_wxid_prefix))
        if cs.redacted_pii:
            parts.append("PII脱敏{}".format(cs.redacted_pii))
        if parts:
            runner.add("  └ {}".format("、".join(parts)))

    runner.add("⏳ 构建对话段…")
    c["builder"].twin_mode = twin_mode
    conversations = c["builder"].build_conversations(cleaned)
    for conv in conversations:
        conv["turn_count"] = len(conv.get("turns", []))
    runner.update("✓ 对话段: {:,} 段（{} 侧为主角）".format(len(conversations), twin_label))

    # --- checkpoint detection ---
    db_mt = _get_db_mtime(config)
    skipped = 0

    # --- 人格分析 ---
    persona_path = Path(config["paths"]["persona_file"])
    _needs_regen3 = not _ckpt_valid(persona_path, db_mt)
    if not _needs_regen3:
        profile = yaml.safe_load(open(persona_path, encoding="utf-8"))
        if not profile.get("vocab_bank"):
            _needs_regen3 = True
    if not _needs_regen3:
        runner.add("⏩ 人格画像已存在，跳过")
        skipped += 1
    else:
        runner.add("⏳ 分析人格特征（{} 侧）…".format(twin_label))
        profile = _timed(runner, lambda: c["analyzer"].analyze(cleaned, twin_mode=twin_mode),
                         lambda e: "⏳ 分析人格特征… 已等待 {}s".format(e))
        persona_path.parent.mkdir(parents=True, exist_ok=True)
        with open(persona_path, "w", encoding="utf-8") as f:
            yaml.dump(profile, f, allow_unicode=True)
        runner.update("✓ 人格画像已保存（含词库）")

    # --- 情绪训练 ---
    from src.personality.emotion_analyzer import EmotionAnalyzer as _EA2
    from src.personality.emotion_tracker import EmotionTracker as _ET2
    emo_path = Path(config["paths"].get("emotion_file", "data/emotion_profile.yaml"))
    if _ckpt_valid(emo_path, db_mt):
        emo_p = yaml.safe_load(open(emo_path, encoding="utf-8"))
        runner.add("⏩ 情绪模型已存在，跳过")
        skipped += 1
    else:
        runner.add("⏳ 训练情绪模型（{} 侧）…".format(twin_label))
        emo_a = _EA2()
        emo_p = _timed(runner, lambda: emo_a.train(cleaned, twin_mode=twin_mode),
                       lambda e: "⏳ 训练情绪模型… 已等待 {}s".format(e))
        emo_a.save(str(emo_path))
        emo_dist = emo_p.get("emotion_distribution", {})
        emo_sorted2 = sorted(emo_dist.items(), key=lambda x: -x[1])
        runner.update("✓ 情绪模型已训练，{}种情绪 ({})".format(
            len(emo_sorted2),
            ", ".join("{}:{}".format(k, v) for k, v in emo_sorted2),
        ))
    _api_cfg2 = config.get("api", {})
    from openai import OpenAI as _OAI_emo2
    _emo_cl2 = _OAI_emo2(
        api_key=_api_cfg2.get("api_key", ""),
        base_url=_api_cfg2.get("base_url"),
        default_headers=_api_cfg2.get("headers", {}),
    )
    c["emotion_tracker"] = _ET2(emo_p, api_client=_emo_cl2, model=_api_cfg2.get("model", "gpt-4o"))

    # --- 思维训练 ---
    think_path = Path(config["paths"].get("thinking_model_file", "data/thinking_model.txt"))
    if _ckpt_valid(think_path, db_mt):
        _thinking2 = think_path.read_text(encoding="utf-8")
        runner.add("⏩ 思维模型已存在（{} 字），跳过".format(len(_thinking2)))
        skipped += 1
    else:
        runner.add("⏳ 训练思维模型（约 3-5 分钟）…")
        try:
            from src.personality.thinking_profiler import ThinkingProfiler as _TP2
            api_cfg = config.get("api", {})
            from openai import OpenAI as _OAI2
            _tp2_client = _OAI2(
                api_key=api_cfg.get("api_key", ""),
                base_url=api_cfg.get("base_url"),
                default_headers=api_cfg.get("headers", {}),
            )
            tp2 = _TP2(_tp2_client, api_cfg.get("model", "gpt-4o"))
            _thinking2 = _retry_api(
                lambda: _timed(runner, lambda: tp2.train(conversations),
                                lambda e: "⏳ 训练思维模型… 已等待 {}s".format(e)),
                runner, "⚠ 思维训练",
            )
            _thinking2 = _thinking2 or ""
            tp2.save(_thinking2, str(think_path))
            runner.update("✓ 思维模型已训练（{} 字，数据驱动）".format(len(_thinking2)))
        except Exception as e:
            logger.warning("Thinking profiler training failed: %s", e)
            _thinking2 = ""
            runner.update("⚠ 思维训练失败: {}".format(e))

    # --- 认知参数提取 ---
    _cog_profile2 = {}
    _cog_path2 = Path("data/cognitive_profile.json")
    _s3_api = config.get("api", {})
    if _ckpt_valid(_cog_path2, db_mt):
        from src.personality.thinking_profiler import ThinkingProfiler as _TP2_cog
        _cog_profile2 = _TP2_cog.load_cognitive_profile()
        runner.add("⏩ 认知参数已存在，跳过")
        skipped += 1
    else:
        try:
            from src.personality.thinking_profiler import ThinkingProfiler as _TP2_cog
            runner.add("⏳ 提取认知风格参数…")
            from openai import OpenAI as _OAI_cog2
            _cog_cl2 = _OAI_cog2(
                api_key=_s3_api.get("api_key", ""),
                base_url=_s3_api.get("base_url"),
                default_headers=_s3_api.get("headers", {}),
            )
            _tp2_cog = _TP2_cog(_cog_cl2, _s3_api.get("model", "gpt-4o"))
            _cog_profile2 = _retry_api(
                lambda: _timed(runner, lambda: _tp2_cog.extract_cognitive_profile(conversations),
                               lambda e: "⏳ 认知参数提取… 已等待 {}s".format(e)),
                runner, "⚠ 认知参数",
            )
            _cog_profile2 = _cog_profile2 or {}
            if _cog_profile2:
                _TP2_cog.save_cognitive_profile(_cog_profile2)
                runner.update("✓ 认知参数已提取")
            else:
                runner.update("⚠ 认知参数数据不足，跳过")
        except Exception as e:
            logger.warning("Cognitive profile extraction failed: %s", e)
            runner.update("⚠ 认知参数提取失败: {}".format(e))

    # --- 情绪边界提取 ---
    _emo_boundaries2 = []
    _eb_path2 = Path("data/emotion_boundaries.json")
    _s3_api_eb = config.get("api", {})
    if _ckpt_valid(_eb_path2, db_mt):
        from src.personality.thinking_profiler import ThinkingProfiler as _TP3_eb
        _emo_boundaries2 = _TP3_eb.load_emotion_boundaries()
        _n_cached2 = sum(len(v) for v in _emo_boundaries2.values()) if isinstance(_emo_boundaries2, dict) else len(_emo_boundaries2)
        runner.add("⏩ 情绪边界已存在（{} 条），跳过".format(_n_cached2))
        skipped += 1
    else:
        try:
            from src.personality.thinking_profiler import ThinkingProfiler as _TP3_eb
            runner.add("⏳ 提取情绪反应边界…")
            from openai import OpenAI as _OAI_eb3
            _eb_cl3 = _OAI_eb3(
                api_key=_s3_api_eb.get("api_key", ""),
                base_url=_s3_api_eb.get("base_url"),
                default_headers=_s3_api_eb.get("headers", {}),
            )
            _tp3_eb = _TP3_eb(_eb_cl3, _s3_api_eb.get("model", "gpt-4o"))
            import src.app as _self_mod3
            _cr3 = getattr(_self_mod3, 'contact_registry', None)
            _emo_boundaries2 = _retry_api(
                lambda: _timed(runner, lambda: _tp3_eb.extract_emotion_boundaries(conversations, contact_registry=_cr3),
                               lambda e: "⏳ 情绪边界提取… 已等待 {}s".format(e)),
                runner, "⚠ 情绪边界",
            )
            _emo_boundaries2 = _emo_boundaries2 or {}
            if _emo_boundaries2:
                _TP3_eb.save_emotion_boundaries(_emo_boundaries2)
                _n_eb2 = sum(len(v) for v in _emo_boundaries2.values()) if isinstance(_emo_boundaries2, dict) else len(_emo_boundaries2)
                runner.update("✓ 情绪边界已提取（{} 条）".format(_n_eb2))
            else:
                runner.update("⚠ 情绪边界数据不足，跳过")
        except Exception as e:
            logger.warning("Emotion boundary extraction failed: %s", e)
            runner.update("⚠ 情绪边界提取失败: {}".format(e))

    # --- 情绪表达风格提取 ---
    _emo_expression2 = {}
    _expr_path2 = Path("data/emotion_expression.json")
    _s3_api_expr = config.get("api", {})
    if _ckpt_valid(_expr_path2, db_mt):
        from src.personality.thinking_profiler import ThinkingProfiler as _TP3_expr
        _emo_expression2 = _TP3_expr.load_emotion_expression()
        runner.add("⏩ 情绪表达风格已存在（{} 种），跳过".format(len(_emo_expression2)))
        skipped += 1
    else:
        try:
            from src.personality.thinking_profiler import ThinkingProfiler as _TP3_expr
            runner.add("⏳ 提取情绪表达风格…")
            from openai import OpenAI as _OAI_expr3
            _expr_cl3 = _OAI_expr3(
                api_key=_s3_api_expr.get("api_key", ""),
                base_url=_s3_api_expr.get("base_url"),
                default_headers=_s3_api_expr.get("headers", {}),
            )
            _tp3_expr = _TP3_expr(_expr_cl3, _s3_api_expr.get("model", "gpt-4o"))
            _emo_expression2 = _retry_api(
                lambda: _timed(runner, lambda: _tp3_expr.extract_emotion_expression_style(conversations),
                               lambda e: "⏳ 情绪表达提取… 已等待 {}s".format(e)),
                runner, "⚠ 情绪表达",
            )
            _emo_expression2 = _emo_expression2 or {}
            if _emo_expression2:
                _TP3_expr.save_emotion_expression(_emo_expression2)
                runner.update("✓ 情绪表达风格已提取（{} 种）".format(len(_emo_expression2)))
            else:
                runner.update("⚠ 情绪表达数据不足，跳过")
        except Exception as e:
            logger.warning("Emotion expression extraction failed: %s", e)
            runner.update("⚠ 情绪表达提取失败: {}".format(e))

    c["prompt_builder"] = PromptBuilder(
        persona_profile=profile,
        cold_start_description=config.get("cold_start_description", ""),
        thinking_model=_thinking2,
        cognitive_profile=_cog_profile2,
        emotion_boundaries=_emo_boundaries2,
        emotion_expression=_emo_expression2,
    )
    c["prompt_builder"].regenerate_guidance()
    runner.update("✓ 指引文件已生成")
    c["chat_engine"].set_components(
        c["retriever"], c["belief_graph"], c["prompt_builder"],
        c["vector_store"], c["emotion_tracker"],
        memory_bank=c.get("memory_bank"),
    )

    # --- 嵌入模型检测 ---
    _emb2 = c["embedder"]
    if _emb2.is_model_cached():
        runner.add("✓ 嵌入模型已就绪")
    else:
        runner.add("⏳ 首次使用，正在下载嵌入模型（约 1-2GB）…")
        try:
            _timed(runner, lambda: _emb2.download_model(),
                   lambda e: "⏳ 下载嵌入模型… 已等待 {}s".format(e))
            runner.update("✓ 嵌入模型下载完成")
        except Exception as e:
            runner.update("⚠ 嵌入模型下载失败: {}，请检查网络连接".format(e))
            return

    # --- 向量化 ---
    vec_count = c["vector_store"].count()
    chroma_sqlite = Path(config["paths"]["chroma_dir"]) / "chroma.sqlite3"
    if vec_count > 0 and _ckpt_valid(chroma_sqlite, db_mt, min_size=1000):
        runner.add("⏩ 向量库已有 {:,} 段，跳过".format(vec_count))
        skipped += 1
    else:
        runner.add("⏳ 向量化写入…")
        try:
            _timed(runner, lambda: c["vector_store"].add_conversations(conversations, c["embedder"]),
                   lambda e: "⏳ 向量化写入… 已等待 {}s".format(e))
            runner.update("✓ 向量库: {:,} 段".format(c["vector_store"].count()))
        except Exception as e:
            runner.update("⚠ 向量化失败: {}".format(e))

    # --- 信念图谱 ---
    bg = c["belief_graph"]
    beliefs_path = Path(config["paths"]["beliefs_file"])
    if bg.count() > 0 and _ckpt_valid(beliefs_path, db_mt, min_size=100):
        runner.add("⏩ 信念图谱已有 {} 条，跳过".format(bg.count()))
        skipped += 1
    else:
        runner.add("⏳ 重建信念图谱（约 1-2 分钟）…")
        old_count = bg.count()
        bg.beliefs.clear()
        bg.contradictions.clear()
        bg._embeddings.clear()
        bg._next_id = 1
        bg.save()
        ll = c["learning_loop"]
        try:
            _timed(runner, lambda: ll.batch_extract_beliefs(conversations, top_n_contacts=1, samples_per_contact=20),
                   lambda e: "⏳ 重建信念图谱… 已等待 {}s（当前 {} 条）".format(e, bg.count()))
            runner.update("✓ 信念图谱已重建: {} → {} 条（从对话数据提取）".format(old_count, bg.count()))
        except Exception as e:
            logger.warning("Belief extraction failed: %s", e)
            runner.update("⚠ 信念图谱重建失败: {}".format(e))

    # --- 记忆提取 ---
    mb = c.get("memory_bank")
    if mb is None:
        from src.memory.memory_bank import MemoryBank
        mb = MemoryBank(filepath="data/memories.json", embedder=c["embedder"])
        c["memory_bank"] = mb
    mem_path = Path("data/memories.json")
    if mb.count() > 0 and _ckpt_valid(mem_path, db_mt, min_size=10):
        high_conf = sum(1 for m in mb.memories if m.confidence >= 0.7)
        runner.add("⏩ 记忆库已有 {} 条（高置信 {} 条），跳过".format(mb.count(), high_conf))
        skipped += 1
    else:
        runner.add("⏳ 提取记忆（约 1-2 分钟）…")
        try:
            mb.clear()
            _api_mb = config.get("api", {})
            from openai import OpenAI as _OAI_mb
            _mb_client = _OAI_mb(
                api_key=_api_mb.get("api_key", ""),
                base_url=_api_mb.get("base_url"),
                default_headers=_api_mb.get("headers", {}),
            )
            _timed(runner, lambda: mb.batch_extract(conversations, _mb_client, _api_mb.get("model", "gpt-4o")),
                   lambda e: "⏳ 提取记忆… 已等待 {}s（当前 {} 条）".format(e, mb.count()))
            high_conf = sum(1 for m in mb.memories if m.confidence >= 0.7)
            runner.update("✓ 记忆库: {} 条（高置信 {} 条）".format(mb.count(), high_conf))
        except Exception as e:
            logger.warning("Memory extraction failed: %s", e)
            runner.update("⚠ 记忆提取失败: {}".format(e))

    # --- 联系人分类 ---
    contacts_path = Path("data/contacts.json")
    if _ckpt_valid(contacts_path, db_mt, min_size=10):
        runner.add("⏩ 联系人数据已存在，跳过")
        skipped += 1
    else:
        runner.add("⏳ 更新联系人库与对象聊天风格…")
        try:
            if contact_registry is None:
                from src.data.contact_registry import ContactRegistry
                contact_registry = ContactRegistry()
            contacts_db = c["parser"].get_contacts()
            contact_registry.build_from_messages(messages, contacts_db)
            if pw in contact_registry.contacts:
                style = c["analyzer"].analyze_per_contact(cleaned, pw)
                if style:
                    contact_registry.set_chat_style(pw, style)
            runner.update(
                "✓ 联系人: {} 个；对象「{}」聊天风格已更新".format(
                    contact_registry.count(),
                    contact_registry.get_display_name(pw),
                )
            )
        except Exception as e:
            logger.warning("Contact registry build failed: %s", e)
            runner.update("⚠ 联系人分类失败: {}".format(e))

    _critical_missing2 = []
    for _cf_label, _cf_path in [
        ("思维模型", "data/thinking_model.txt"),
        ("认知参数", "data/cognitive_profile.json"),
        ("情绪边界", "data/emotion_boundaries.json"),
        ("情绪表达", "data/emotion_expression.json"),
    ]:
        if not Path(_cf_path).exists() or Path(_cf_path).stat().st_size < 50:
            _critical_missing2.append(_cf_label)

    if _critical_missing2:
        runner.add("\n⚠️ 训练未完成！以下关键步骤因 API 错误未成功：{}。请检查 API 后重新训练。".format("、".join(_critical_missing2)))
        runner.error = "关键步骤失败: " + "、".join(_critical_missing2)
    elif skipped:
        runner.add("\n🎉 学习完成！跳过了 {} 个已完成步骤 ⏩".format(skipped))
    else:
        runner.add("\n🎉 学习完成！所有步骤已成功。")


def import_data():
    """Start (or join) the training pipeline. Returns (text, timer_update)."""
    if components is None:
        return "系统未初始化：{}".format(init_error), gr.Timer(active=False)
    from src.data.partner_config import load_partner_wxid
    if not load_partner_wxid().strip():
        return (
            "请先在「选择 TA」中扫描联系人并保存对象；学习仅使用该对象的聊天记录。",
            gr.Timer(active=False),
        )
    runner = TrainingRunner.instance()
    if runner.is_running():
        return "\n".join(str(s) for s in runner.get_steps()), gr.Timer(active=True)
    runner.start(_import_pipeline, mode="text")
    return "⏳ 训练启动中…", gr.Timer(active=True)


# ---------------------------------------------------------------------------
# Callback: Analytics dashboard
# ---------------------------------------------------------------------------

def load_analytics():
    """Return all HTML needed for the analytics tab."""
    no_data = "<p style='text-align:center;padding:40px;opacity:.5'>请先导入数据</p>"
    if components is None:
        return (no_data, no_data, no_data, no_data, no_data, no_data, no_data)

    try:
        stats = components["parser"].get_stats()
    except Exception as e:
        err = "<p style='color:red'>加载统计失败: {}</p>".format(e)
        return (err, "", "", "", "", "", "")

    if stats["total_messages"] == 0:
        return (no_data, no_data, no_data, no_data, no_data, no_data, no_data)

    total_msg = "{:,}".format(stats["total_messages"])
    date_range = "{} ~ {}".format(stats["date_start"], stats["date_end"])
    sent_recv = "{:,} / {:,}".format(stats["sent"], stats["received"])

    belief_count = components["belief_graph"].count()
    vec_count = components["vector_store"].count()

    cards = (
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">'
        + _stat_card(total_msg, "总消息数")
        + _stat_card(stats["unique_talkers"], "活跃联系人")
        + _stat_card(date_range, "时间跨度")
        + '</div>'
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">'
        + _stat_card(sent_recv, "发送 / 接收")
        + _stat_card(belief_count, "信念条目")
        + _stat_card("{:,}".format(vec_count), "向量记忆段")
        + _stat_card(contact_registry.count() if contact_registry else 0, "已识别联系人")
        + '</div>'
    )

    top_named = stats.get("top_contacts_named", stats.get("top_contacts", []))[:15]
    contacts_html = _build_hbar_chart_html(top_named, "联系人消息量 Top 15") if top_named else no_data

    hourly = stats.get("hourly_distribution", {})
    hourly_data = [("{:02d}".format(h), hourly.get(h, 0)) for h in range(24)]
    hourly_html = _build_vbar_chart_html(hourly_data, "24 小时消息分布") if hourly else no_data

    monthly = stats.get("monthly_distribution", {})
    monthly_html = _build_hbar_chart_html(
        sorted(monthly.items()), "月度消息趋势"
    ) if monthly else no_data

    relationship_html = _build_relationship_html()
    belief_summary_html = _build_belief_summary_html()
    persona_html = _build_persona_html()

    return (cards, contacts_html, hourly_html, monthly_html, relationship_html, belief_summary_html, persona_html)


def _build_hbar_chart_html(data: list[tuple], title: str = "") -> str:
    """Horizontal bar chart rendered as HTML."""
    if not data:
        return ""
    max_val = max(v for _, v in data) or 1
    bars = []
    for label, count in data:
        pct = count / max_val * 100
        count_str = "{:,}".format(count)
        bars.append(
            '<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
            '<span style="min-width:80px;font-size:.85em;text-align:right;overflow:hidden;'
            'text-overflow:ellipsis;white-space:nowrap">' + str(label) + '</span>'
            '<div style="flex:1;background:var(--block-background-fill);border-radius:4px;overflow:hidden">'
            '<div style="background:var(--color-accent);height:22px;border-radius:4px;'
            'width:{:.1f}%;min-width:2px;transition:width .3s"></div>'.format(pct) +
            '</div>'
            '<span style="min-width:50px;font-size:.8em;opacity:.7">' + count_str + '</span>'
            '</div>'
        )
    header = '<h4 style="margin:0 0 8px">' + title + '</h4>' if title else ''
    return header + '<div style="padding:4px 0">' + "".join(bars) + '</div>'


def _build_vbar_chart_html(data: list[tuple], title: str = "") -> str:
    """Vertical bar chart rendered as HTML (e.g. for 24h distribution)."""
    if not data:
        return ""
    max_val = max(v for _, v in data) or 1
    cols = []
    for label, count in data:
        pct = count / max_val * 100
        cols.append(
            '<div style="display:flex;flex-direction:column;align-items:center;flex:1;min-width:0">'
            '<div style="flex:1;width:100%;display:flex;align-items:flex-end;min-height:150px">'
            '<div style="width:100%;background:var(--color-accent);border-radius:3px 3px 0 0;'
            'min-height:2px;height:{:.1f}%"></div>'.format(pct) +
            '</div>'
            '<span style="font-size:.65em;margin-top:4px;opacity:.7">' + str(label) + '</span>'
            '</div>'
        )
    header = '<h4 style="margin:0 0 8px">' + title + '</h4>' if title else ''
    return (
        header +
        '<div style="display:flex;gap:2px;padding:4px 0;align-items:stretch">'
        + "".join(cols)
        + '</div>'
    )


def _build_relationship_html() -> str:
    """Render relationship distribution from contact registry."""
    if contact_registry is None or contact_registry.count() == 0:
        return "<p style='text-align:center;opacity:.5'>联系人数据未导入</p>"
    from src.data.contact_registry import RELATIONSHIP_LABELS
    from collections import Counter
    rel_counts: Counter = Counter()
    for c in contact_registry.contacts.values():
        rel = c.get("relationship", "unknown")
        label = RELATIONSHIP_LABELS.get(rel, rel)
        rel_counts[label] += 1
    data = rel_counts.most_common()
    return _build_hbar_chart_html(data, "联系人关系分布")


def _build_belief_summary_html() -> str:
    """Render belief graph summary."""
    if components is None:
        return ""
    bg = components["belief_graph"]
    all_beliefs = bg.query_all() if hasattr(bg, "query_all") else []
    if not all_beliefs:
        return "<p style='text-align:center;opacity:.5'>暂无信念数据，训练后自动生成</p>"
    high_conf = [b for b in all_beliefs if b.get("confidence", 0) >= 0.8]
    topics = [b.get("topic", "") for b in all_beliefs if b.get("topic")]
    from collections import Counter
    import jieba
    topic_counts = Counter()
    for t in topics:
        for w in jieba.cut(t):
            w = w.strip()
            if len(w) >= 2:
                topic_counts[w] += 1
    top_topic_words = topic_counts.most_common(20)

    html = '<h4 style="margin:0 0 8px">信念图谱概览</h4>'
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">'
    html += _stat_card(len(all_beliefs), "总信念数")
    html += _stat_card(len(high_conf), "高置信度信念")
    html += _stat_card("{:.0%}".format(len(high_conf) / len(all_beliefs)) if all_beliefs else "0%", "高置信度占比")
    html += '</div>'
    if top_topic_words:
        html += '<h4 style="margin:8px 0">信念关键词</h4>'
        html += _wordcloud_html(top_topic_words)
    sample_beliefs = sorted(all_beliefs, key=lambda b: b.get("confidence", 0), reverse=True)[:5]
    if sample_beliefs:
        html += '<h4 style="margin:12px 0 8px">最强信念 Top 5</h4>'
        for b in sample_beliefs:
            conf = b.get("confidence", 0)
            html += '<div style="padding:6px 12px;margin:4px 0;background:var(--block-background-fill);border-radius:6px;border-left:3px solid var(--color-accent)">'
            html += '<b>{}</b>：{}'.format(b.get("topic", ""), b.get("stance", ""))
            html += ' <span style="opacity:.5;font-size:.85em">({:.0%})</span>'.format(conf)
            html += '</div>'
    return html


def _build_persona_html() -> str:
    if components is None:
        return ""
    config = components["config"]
    persona_path = Path(config["paths"]["persona_file"])
    if not persona_path.exists():
        return "<p style='text-align:center;padding:20px;opacity:.5'>尚未生成人格画像，请先训练数据</p>"

    with open(persona_path, encoding="utf-8") as f:
        p = yaml.safe_load(f) or {}

    if not p.get("total_messages_analyzed"):
        return "<p style='text-align:center;padding:20px;opacity:.5'>尚未生成人格画像</p>"

    dist = p.get("message_length_distribution", {})
    punc = p.get("punctuation_style", {})
    resp_time = p.get("avg_response_time_seconds")
    resp_str = f"{resp_time:.0f}秒" if resp_time else "N/A"

    avg_len = "{:.1f} 字".format(p.get("avg_message_length", 0))
    emoji_f = "{:.1%}".format(p.get("emoji_frequency", 0))
    vocab_r = "{:.2%}".format(p.get("vocabulary_richness", 0))
    short_p = "{:.0f}%".format(dist.get("short", 0))
    med_p = "{:.0f}%".format(dist.get("medium", 0))
    long_p = "{:.0f}%".format(dist.get("long", 0))

    metrics = (
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">'
        + _stat_card(avg_len, "平均消息长度")
        + _stat_card(emoji_f, "表情使用频率")
        + _stat_card(vocab_r, "词汇丰富度")
        + '</div>'
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px">'
        + _stat_card(resp_str, "平均回复时间")
        + _stat_card(short_p, "短消息占比")
        + _stat_card(med_p, "中等消息占比")
        + _stat_card(long_p, "长消息占比")
        + '</div>'
    )

    exc_f = "{:.2f}/条".format(punc.get("exclamation_freq", 0))
    ell_f = "{:.2f}/条".format(punc.get("ellipsis_freq", 0))
    que_f = "{:.2f}/条".format(punc.get("question_freq", 0))

    punc_html = (
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">'
        + _stat_card(exc_f, "感叹号频率")
        + _stat_card(ell_f, "省略号频率")
        + _stat_card(que_f, "问号频率")
        + '</div>'
    )

    phrases = p.get("top_phrases", [])
    cloud = _wordcloud_html(phrases)

    total_analyzed = "{:,}".format(p.get("total_messages_analyzed", 0))
    return (
        '<h3 style="margin:0 0 12px">人格画像 (' + total_analyzed + ' 条消息分析)</h3>'
        + metrics
        + '<h4 style="margin:8px 0">标点风格</h4>' + punc_html
        + '<h4 style="margin:8px 0">高频短语</h4>' + cloud
    )


# ---------------------------------------------------------------------------
# Callback: Belief graph
# ---------------------------------------------------------------------------

def build_contact_registry_callback():
    """Scan messages and build the contact registry."""
    if components is None:
        return "<p style='color:red'>系统未初始化</p>", [], gr.update()
    try:
        global contact_registry
        if contact_registry is None:
            from src.data.contact_registry import ContactRegistry
            contact_registry = ContactRegistry()
        raw_dir = str(Path(components["config"]["paths"].get("raw_db_dir", "data/raw")).resolve())
        components["parser"].set_db_dir(raw_dir)
        parser = components["parser"]
        messages = parser.get_all_text_messages()
        used_fallback = False
        if not messages:
            messages = parser.get_messages()
            used_fallback = True
        contacts_db = parser.get_contacts()
        contact_registry.build_from_messages(messages, contacts_db)
        table_data, dropdown_choices = _build_contact_table_and_dropdown()
        n_msg_dbs = len(getattr(parser, "message_dbs", []) or [])
        if contact_registry.count() == 0:
            hint = (
                "未读到任何会话记录。请确认：①「连接」里解密已成功；② 数据目录 <code>{}</code> 下存在 "
                "<code>message/message_*.db</code>；③ 若曾修改过 <code>paths.raw_db_dir</code>，路径需与解密输出一致。"
                "<br>当前检测到消息库文件数：<b>{}</b>。"
            ).format(raw_dir, n_msg_dbs)
            return (
                '<div class="step-card step-fail">扫描完成，共 0 个联系人。<br><small>{}</small></div>'.format(hint),
                [],
                gr.update(choices=[("（无联系人数据）", "")]),
            )
        extra = ""
        if used_fallback:
            extra = "<br><small>提示：纯文本消息列为空，已用全部消息类型统计联系人（选对象后训练仍以文本为主）。</small>"
        msg = '<div class="step-card step-ok">扫描完成，共 {} 个联系人（🤖=AI判断 ✋=手动设置）{}</div>'.format(
            contact_registry.count(), extra,
        )
        return msg, table_data, gr.update(choices=dropdown_choices)
    except Exception as e:
        return '<div class="step-card step-fail">扫描失败: {}</div>'.format(e), [], gr.update()


def _build_contact_table_and_dropdown():
    """Build table data and dropdown choices from contact registry."""
    from src.data.contact_registry import RELATIONSHIP_LABELS
    if contact_registry is None or contact_registry.count() == 0:
        return [], [("（无联系人数据）", "")]
    top = contact_registry.get_top_contacts(50)
    table_data = []
    dropdown_choices = []
    for c in top:
        wxid = c["wxid"]
        name = contact_registry.get_display_name(wxid)
        rel = c.get("relationship", "unknown")
        rel_label = RELATIONSHIP_LABELS.get(rel, "未知")
        count = c.get("message_count", 0)
        auto = c.get("auto_detected", True)
        source = "🤖 AI" if auto else "✋ 手动"
        table_data.append([name, rel_label, f"{count:,}", source, wxid])
        dropdown_choices.append((f"{name} [{rel_label}] ({count:,}条)", wxid))
    return table_data, dropdown_choices


def save_contact_relationship(wxid: str, relationship: str):
    """Update a contact's relationship and refresh table."""
    if not contact_registry or not wxid or not relationship:
        return "<span style='color:#f87171'>请先选择联系人和关系类型</span>", [], gr.update()
    from src.data.contact_registry import RELATIONSHIP_LABELS
    contact_registry.set_relationship(wxid.strip(), relationship)
    name = contact_registry.get_display_name(wxid.strip())
    label = RELATIONSHIP_LABELS.get(relationship, relationship)
    gr.Info(f"已将「{name}」的关系设为「{label}」")
    table_data, dropdown_choices = _build_contact_table_and_dropdown()
    return (
        f"<span style='color:#65a88a'>✓ 已保存：{name} → {label}（✋ 手动）</span>",
        table_data,
        gr.update(choices=dropdown_choices),
    )


def query_beliefs(topic: str) -> list[list[str]]:
    if components is None:
        return [["系统未初始化", "", "", "", ""]]
    bg = components["belief_graph"]
    beliefs = bg.query_by_topic(topic) if topic.strip() else bg.query_all()
    rows = []
    for b in beliefs:
        rows.append([
            b.get("topic", ""),
            b.get("stance", ""),
            b.get("condition", ""),
            str(b.get("confidence", "")),
            b.get("source", ""),
        ])
    return rows if rows else [["暂无信念数据", "", "", "", ""]]


# ---------------------------------------------------------------------------
# Callback: Memory bank
# ---------------------------------------------------------------------------

MEMORY_TYPE_LABELS = {
    "fact": "事实", "event": "经历", "preference": "偏好",
    "plan": "计划", "relationship": "人际", "habit": "习惯",
}


def query_memories(search: str) -> list[list]:
    mb = components.get("memory_bank") if components else None
    if mb is None or mb.count() == 0:
        return [["暂无记忆数据", "", "", "", "", ""]]
    if search.strip():
        hits = mb.query(search.strip(), top_k=30, min_confidence=0.0)
    else:
        hits = sorted(mb.memories, key=lambda m: -m.confidence)
    rows = []
    for m in hits:
        rows.append([
            str(m.id),
            MEMORY_TYPE_LABELS.get(m.type, m.type),
            m.content,
            f"{m.confidence:.0%}",
            str(m.mentions),
            "确定" if m.confidence >= 0.7 else ("可能" if m.confidence >= 0.4 else "存疑"),
        ])
    return rows if rows else [["无匹配结果", "", "", "", "", ""]]


def edit_memory(mem_id: str, new_content: str, new_confidence: str):
    mb = components.get("memory_bank") if components else None
    if mb is None:
        return "<span style='color:#f87171'>记忆库未初始化</span>", []
    mid = int(mem_id) if mem_id.strip().isdigit() else 0
    target = next((m for m in mb.memories if m.id == mid), None)
    if target is None:
        return "<span style='color:#f87171'>未找到 ID={} 的记忆</span>".format(mem_id), query_memories("")
    if new_content.strip():
        target.content = new_content.strip()
        if mb.embedder:
            target.embedding = mb.embedder.embed_single(target.content)
    if new_confidence.strip():
        try:
            target.confidence = max(0.0, min(1.0, float(new_confidence)))
        except ValueError:
            pass
    mb.save()
    return "<span style='color:#65a88a'>✓ 已更新记忆 #{}</span>".format(mid), query_memories("")


def delete_memory(mem_id: str):
    mb = components.get("memory_bank") if components else None
    if mb is None:
        return "<span style='color:#f87171'>记忆库未初始化</span>", []
    mid = int(mem_id) if mem_id.strip().isdigit() else 0
    before = mb.count()
    mb.memories = [m for m in mb.memories if m.id != mid]
    if mb.count() == before:
        return "<span style='color:#f87171'>未找到 ID={}</span>".format(mem_id), query_memories("")
    mb.save()
    return "<span style='color:#65a88a'>✓ 已删除记忆 #{}</span>".format(mid), query_memories("")


def add_memory_manual(mem_type: str, content: str):
    mb = components.get("memory_bank") if components else None
    if mb is None:
        return "<span style='color:#f87171'>记忆库未初始化</span>", []
    if not content.strip():
        return "<span style='color:#f87171'>请输入记忆内容</span>", query_memories("")
    m = mb.add(mem_type or "fact", content.strip(), certainty="high", source="manual")
    mb.save()
    return (
        "<span style='color:#65a88a'>✓ 已添加记忆 #{} (置信度 {:.0%})</span>".format(m.id, m.confidence),
        query_memories(""),
    )


# ---------------------------------------------------------------------------
# Callback: System info
# ---------------------------------------------------------------------------

def get_system_info() -> str:
    if components is None:
        return f"系统未初始化：{init_error}"

    c = components
    config = c["config"]
    lines = []

    vec_count = c["vector_store"].count()
    lines.append(f"向量库对话段数量: {vec_count}")

    belief_count = c["belief_graph"].count()
    lines.append(f"信念数量: {belief_count}")

    lines.append(f"\n模型: {config['api']['provider']} / {config['api']['model']}")
    lines.append(f"嵌入模型: {config['embedding']['model']}")
    if config["api"].get("base_url"):
        lines.append(f"API Base URL: {config['api']['base_url']}")

    db_dir = Path(config["paths"]["raw_db_dir"])
    db_count = len(list(db_dir.rglob("*.db"))) if db_dir.exists() else 0
    lines.append(f"\n数据库目录: {db_dir} ({db_count} 个 .db 文件)")

    from src.data.partner_config import load_partner_wxid, load_twin_mode
    pw = load_partner_wxid().strip()
    if pw and contact_registry:
        lines.append("\n已确认对象: {} ({})".format(contact_registry.get_display_name(pw), pw))
    elif pw:
        lines.append("\n已确认对象 wxid: {}".format(pw))
    else:
        lines.append("\n已确认对象: （未设置，请在「选择 TA」中选择）")

    tm = load_twin_mode()
    lines.append("训练模式: {}".format("训练自己的分身" if tm == "self" else "训练对象的分身"))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    with gr.Blocks(
        theme=gr.themes.Soft(
            primary_hue=gr.themes.colors.rose,
            secondary_hue=gr.themes.colors.amber,
            neutral_hue=gr.themes.colors.stone,
            font=[gr.themes.GoogleFont("Inter"), gr.themes.GoogleFont("Noto Sans SC"),
                  "ui-sans-serif", "system-ui", "sans-serif"],
            font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
        ).set(
            body_background_fill="#faf7f5",
            body_background_fill_dark="#1a1617",
            block_background_fill="#ffffff",
            block_background_fill_dark="#262122",
            block_border_color="#e6dcd8",
            block_border_color_dark="#3a3234",
            border_color_primary="#e6dcd8",
            input_background_fill="#ffffff",
            input_background_fill_dark="#2c2627",
            button_primary_background_fill="#b07c84",
            button_primary_background_fill_hover="#9a6a73",
            button_primary_text_color="#ffffff",
            shadow_drop="0 1px 3px rgba(61,44,48,0.06)",
            shadow_drop_lg="0 4px 12px rgba(61,44,48,0.08)",
        ),
        title="心译",
        css=CUSTOM_CSS,
    ) as demo:
        if init_error:
            gr.Markdown(
                f"> **初始化警告**: {init_error}\n>\n"
                f"> 请检查 `config.yaml` 配置后重启。"
            )

        init_status = _detect_pipeline_status()
        is_ready = init_status["has_training"]

        def _load_api_fields():
            try:
                cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8")) or {}
                api = cfg.get("api", {})
                return (
                    api.get("api_key", ""),
                    api.get("base_url", ""),
                    api.get("model", ""),
                    api.get("provider", "openai"),
                )
            except Exception:
                return "", "", "", "openai"

        def _save_api(provider, model, key, base_url):
            if not (key or "").strip():
                return '<span style="color:#f87171">API Key 不能为空</span>'
            try:
                cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8")) or {}
            except Exception:
                cfg = {}
            if "api" not in cfg:
                cfg["api"] = {}
            cfg["api"]["provider"] = (provider or "openai").strip()
            cfg["api"]["model"] = (model or "").strip()
            cfg["api"]["api_key"] = (key or "").strip()
            cfg["api"]["base_url"] = (base_url or "").strip() or None
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

            global components, init_error, contact_registry, session_mgr, persona_mgr
            try:
                _cfg = load_config()
                components = init_components(_cfg)
                from src.engine.session import SessionManager
                session_mgr = SessionManager(directory="data/sessions")
                from src.engine.persona import PersonaManager
                persona_mgr = PersonaManager(directory="data/personas")
                from src.data.contact_registry import ContactRegistry
                contact_registry = ContactRegistry()
                ensure_couple_personas()
                import threading
                threading.Thread(target=components["embedder"].warmup, daemon=True).start()
                init_error = None
                logger.info("API 配置保存后重新初始化成功")
                return '<span style="color:#65a88a">✓ 已保存并初始化完成，可以开始使用。</span>'
            except Exception as e:
                init_error = str(e)
                logger.error("API 保存后重新初始化失败: %s", e)
                return f'<span style="color:#65a88a">✓ 已保存。</span><span style="color:#f59e0b"> 初始化失败（{e}），请检查配置后刷新页面。</span>'

        _ak, _bu, _md, _pv = _load_api_fields()
        _has_api = bool(_ak)
        _has_partner = init_status.get("has_partner", False)
        _has_decrypted = init_status.get("has_decrypted", False)

        def _step_done_html(label, done, detail=""):
            icon = "✅" if done else "⬜"
            d = f' <span style="opacity:.6">— {detail}</span>' if detail else ""
            return f'<span style="font-size:.95em">{icon} {label}{d}</span>'

        def _setup1_status_html():
            st = _detect_pipeline_status()
            ak2, bu2, md2, pv2 = _load_api_fields()
            has_api2 = bool(ak2)
            hd = st.get("has_decrypted", False)
            return (
                _step_done_html("API 已配置", has_api2, pv2 + " / " + md2 if has_api2 else "未配置") + "<br>"
                + _step_done_html("解密工具", st["has_scanner"], "已编译" if st["has_scanner"] else "") + "<br>"
                + _step_done_html("密钥提取", st["has_keys"], "{} 个密钥".format(st.get("key_count", 0)) if st["has_keys"] else "") + "<br>"
                + _step_done_html("数据库解密", hd, "{} 个数据库".format(st.get("db_count", 0)) if hd else "")
            )

        def _step3_decrypt_banner_html():
            st = _detect_pipeline_status()
            if st.get("has_decrypted"):
                return '<span style="color:#65a88a">✓ 数据库已解密（{} 个）。</span>'.format(st.get("db_count", 0))
            return STEP3_GUIDE_HTML

        with gr.Tabs(elem_id="main-tabs") as main_tabs:

            # ================================================================
            # Setup Tab 1: API 配置与解密
            # ================================================================
            with gr.Tab("连接", id="tab-setup-1"):

                gr.Markdown("### 连接你的 AI 服务")

                # -- status overview (refreshed after decrypt via decrypt_timer) --
                setup1_status = gr.HTML(value=_setup1_status_html())

                # -- API config --
                gr.Markdown("---\n#### API 配置")
                if _has_api:
                    gr.Markdown(
                        '<span style="color:#65a88a">✓ API 已配置完成。如需修改，可在「设置」中操作。</span>'
                    )
                else:
                    gr.Markdown("填写大模型 API 信息后保存。")
                with gr.Row():
                    api_provider_input = gr.Dropdown(
                        label="Provider", choices=["openai", "anthropic", "gemini"],
                        value=_pv, scale=1, interactive=not _has_api,
                    )
                    api_model_input = gr.Textbox(label="Model", value=_md, scale=2, interactive=not _has_api)
                with gr.Row():
                    api_key_input = gr.Textbox(label="API Key", value=_ak, type="password", scale=3, interactive=not _has_api)
                with gr.Row():
                    api_base_input = gr.Textbox(label="Base URL（留空用默认）", value=_bu, scale=3, interactive=not _has_api)
                if not _has_api:
                    save_api_btn = gr.Button("保存 API 配置", variant="primary")
                    save_api_result = gr.HTML()
                    save_api_btn.click(
                        fn=_save_api,
                        inputs=[api_provider_input, api_model_input, api_key_input, api_base_input],
                        outputs=save_api_result,
                    )

                # -- decrypt tool + keys --
                gr.Markdown("---\n#### 解密工具准备")
                if init_status["has_scanner"]:
                    gr.HTML('<span style="color:#65a88a">✓ 解密工具已就绪。</span>')
                else:
                    gr.HTML(STEP1_GUIDE_HTML)
                step1_btn = gr.Button(
                    "✓ 已准备" if init_status["has_scanner"] else "自动准备解密工具",
                    variant="secondary" if init_status["has_scanner"] else "primary",
                    interactive=not init_status["has_scanner"],
                )
                step1_output = gr.HTML()

                gr.Markdown("---\n#### 提取密钥")
                repo_dir = Path("vendor/wechat-decrypt").resolve()
                if init_status["has_keys"]:
                    gr.HTML('<span style="color:#65a88a">✓ 密钥已提取（{} 个）。</span>'.format(init_status.get("key_count", 0)))
                else:
                    gr.HTML(_build_step2_guide_html(str(repo_dir)))
                gr.HTML(
                    "<div style='font-size:0.82em;opacity:0.88;line-height:1.65;margin:8px 0 0;color:var(--body-text-color)'>"
                    "<strong>说明：</strong>若 <code>all_keys.json</code> 里缺少 <code>message/message_0.db</code> 等主消息库密钥，"
                    "私聊无法解密，扫描联系人可能为 0。请保持微信<strong>已登录并运行</strong>后，点「重新提取密钥」查看终端命令，"
                    "再点「重新检测密钥」，必要时在第 3 步重新解密。"
                    "</div>"
                )
                with gr.Row():
                    step2_btn = gr.Button(
                        "重新检测密钥" if init_status["has_keys"] else "检测密钥",
                        variant="primary" if not init_status["has_keys"] else "secondary",
                    )
                    step2_reextract_btn = gr.Button("重新提取密钥", variant="secondary")
                step2_output = gr.HTML()

                gr.Markdown("---\n#### 解密数据库")
                step3_decrypt_banner = gr.HTML(value=_step3_decrypt_banner_html())
                gr.HTML(
                    "<div style='font-size:0.82em;opacity:0.88;line-height:1.65;margin:8px 0 0'>"
                    "重新提取密钥或更换数据源后，可随时点「重新解密」覆盖 <code>data/raw</code> 下的解密结果。"
                    "</div>"
                )
                step3_btn = gr.Button(
                    "重新解密" if _has_decrypted else "开始解密",
                    variant="secondary" if _has_decrypted else "primary",
                    size="lg",
                )
                step3_output = gr.HTML()

                with gr.Accordion("高级：已有解密数据库？直接导入", open=False):
                    with gr.Row():
                        path_input = gr.Textbox(
                            label="解密目录路径",
                            placeholder="例如: /path/to/wechat-decrypt/decrypted",
                            scale=5,
                        )
                        link_btn = gr.Button("导入目录", variant="primary", scale=1)
                    scan_info = gr.Textbox(label="扫描结果", interactive=False, lines=2)
                    link_result = gr.HTML()

                if _has_decrypted or _has_api:
                    gr.Markdown(
                        '\n<div style="text-align:center;margin-top:16px">'
                        '<span style="font-size:1.1em">完成后，前往 <b>「选择 TA」</b> →</span>'
                        '</div>'
                    )

                decrypt_timer = gr.Timer(value=3, active=False)

                def _decrypt_poll():
                    r = TrainingRunner.instance()
                    steps = r.get_steps()
                    active = r.is_running() and not r.done
                    skip = gr.update()
                    st_up = skip
                    ban_up = skip
                    if not steps:
                        return skip, skip, gr.Timer(active=active), st_up, ban_up
                    html = _step_html(steps)
                    if r.mode == "step1":
                        return html, skip, gr.Timer(active=active), st_up, ban_up
                    if r.mode == "step3":
                        out3 = html
                        if r.done:
                            st_up = _setup1_status_html()
                            ban_up = _step3_decrypt_banner_html()
                        return skip, out3, gr.Timer(active=active), st_up, ban_up
                    return skip, skip, gr.Timer(active=active), st_up, ban_up

                decrypt_timer.tick(
                    fn=_decrypt_poll,
                    outputs=[step1_output, step3_output, decrypt_timer, setup1_status, step3_decrypt_banner],
                )

                step1_btn.click(fn=run_step1_prepare, outputs=[step1_output, decrypt_timer])
                step2_btn.click(fn=run_step2_check_keys, outputs=step2_output)
                step2_reextract_btn.click(fn=run_step2_reextract_instructions, outputs=step2_output)
                step3_btn.click(fn=run_step3_decrypt_only, outputs=[step3_output, decrypt_timer])
                def _link_external_dir_ui(path_str: str):
                    h, s = link_external_dir(path_str)
                    return h, s, _setup1_status_html(), _step3_decrypt_banner_html()

                link_btn.click(
                    fn=_link_external_dir_ui,
                    inputs=path_input,
                    outputs=[link_result, scan_info, setup1_status, step3_decrypt_banner],
                )
                path_input.submit(
                    fn=_link_external_dir_ui,
                    inputs=path_input,
                    outputs=[link_result, scan_info, setup1_status, step3_decrypt_banner],
                )

            # ================================================================
            # Setup Tab 2: 联系人与对象
            # ================================================================
            with gr.Tab("选择 TA", id="tab-setup-2"):

                gr.Markdown("### 告诉心译，TA 是谁")

                from src.data.partner_config import load_partner_wxid as _lpw
                _cur_partner = _lpw().strip()

                setup2_status = gr.HTML(value=(
                    _step_done_html("对象已确认", _has_partner, _cur_partner if _has_partner else "未选择") + "<br>"
                    + _step_done_html("训练模式", True, "训练{}的分身".format("自己" if _current_twin_mode() == "self" else "对象"))
                ))

                gr.Markdown("---\n#### 扫描联系人")
                if _has_partner:
                    gr.HTML('<span style="color:#65a88a">✓ 对象已确认：<b>{}</b>。如需更换，请重新扫描。</span>'.format(_cur_partner))

                def _partner_scan_only():
                    msg, _tbl, _dd = build_contact_registry_callback()
                    return msg, gr.update(choices=partner_candidate_choices())

                scan_partner_btn = gr.Button("扫描联系人", variant="primary")
                scan_partner_html = gr.HTML()
                partner_pick = gr.Dropdown(
                    label="选择对象",
                    choices=partner_candidate_choices(),
                    interactive=True,
                    allow_custom_value=False,
                )
                save_partner_btn = gr.Button("保存为我的对象", variant="primary")
                save_partner_html = gr.HTML()

                scan_partner_btn.click(
                    fn=_partner_scan_only,
                    outputs=[scan_partner_html, partner_pick],
                )
                save_partner_btn.click(
                    fn=save_partner_selection,
                    inputs=[partner_pick],
                    outputs=[save_partner_html, partner_pick],
                )

                gr.Markdown("---\n#### 训练模式")
                gr.Markdown(
                    "- **训练自己**：学你的说话风格，生成你的分身（对象跟「你」聊）\n"
                    "- **训练对象**：学对象的说话风格，生成 TA 的分身（你跟「TA」聊）\n\n"
                    "如果两个都要，先训练一个，再克隆项目另起一个 Dashboard。"
                )
                twin_mode_radio = gr.Radio(
                    choices=[("训练自己的分身", "self"), ("训练对象的分身", "partner")],
                    value=_current_twin_mode(),
                    label="训练模式",
                )
                twin_mode_html = gr.HTML()
                twin_mode_radio.change(
                    fn=save_twin_mode_selection,
                    inputs=[twin_mode_radio],
                    outputs=[twin_mode_html],
                )

                gr.Markdown("---\n#### 开始学习")
                gr.Markdown("确认对象和训练模式后，点击开始。")

                if is_ready:
                    gr.Markdown(
                        '<div style="padding:16px;background:#065f46;border-radius:10px;text-align:center;margin:12px 0">'
                        '<span style="color:#6ee7b7;font-size:1.2em;font-weight:600">✅ 学习完成！所有功能已解锁。</span>'
                        '</div>'
                    )

                train_btn = gr.Button(
                    "重新学习" if is_ready else "开始学习",
                    variant="primary",
                    size="lg",
                )
                train_output = gr.Textbox(label="学习进度", lines=12, interactive=False, show_copy_button=True)

                progress_timer = gr.Timer(value=3, active=False)

                def _tab_vis():
                    ready = _detect_pipeline_status()["has_training"]
                    vis = gr.update(visible=True) if ready else gr.update()
                    return [vis] * 6

                def _render_runner(r):
                    steps = r.get_steps()
                    active = r.is_running() and not r.done
                    skip = gr.update()
                    tab_updates = _tab_vis() if (r.done and not r.error) else [skip] * 6
                    base = [skip, gr.Timer(active=active)]
                    if not steps:
                        return base + tab_updates
                    if r.mode == "text":
                        base[0] = "\n".join(str(s) for s in steps)
                    elif r.mode in ("step3", "step1"):
                        base[0] = _step_html(steps)
                    else:
                        base[0] = "\n".join(str(s) for s in steps)
                    return base + tab_updates

                def _poll_tick():
                    return _render_runner(TrainingRunner.instance())

                def _on_page_load():
                    return _render_runner(TrainingRunner.instance())

                train_btn.click(fn=import_data, outputs=[train_output, progress_timer])

            # ================================================================
            # Tab: Chat — 心译对话（partner persona + advisor）
            # ================================================================
            with gr.Tab("心译对话", id="tab-chat", visible=is_ready) as tab_chat:
                from src.engine.partner_advisor import (
                    PartnerAdvisor,
                    AdvisorSession,
                    AdvisorSessionManager,
                )
                from src.mediation.mediator import ConflictMediator

                _adv_mgr = AdvisorSessionManager()
                _adv_state = gr.State(value=None)  # current session id

                def _init_advisor():
                    if not components:
                        return None
                    from src.data.partner_config import load_twin_mode as _ltm_adv
                    from openai import OpenAI as _AdvOAI
                    api_cfg = components["config"]["api"]
                    client = _AdvOAI(
                        api_key=api_cfg.get("api_key", ""),
                        base_url=api_cfg.get("base_url"),
                        default_headers=api_cfg.get("headers", {}),
                    )
                    persona_path = Path(components["config"]["paths"]["persona_file"])
                    persona_profile = {}
                    if persona_path.exists():
                        import yaml as _adv_yaml
                        with open(persona_path, encoding="utf-8") as f:
                            persona_profile = _adv_yaml.safe_load(f) or {}
                    from src.personality.emotion_analyzer import EmotionAnalyzer as _AdvEA
                    emo_path = components["config"]["paths"].get("emotion_file", "data/emotion_profile.yaml")
                    emo_profile = _AdvEA.load(emo_path)
                    tw = _ltm_adv()
                    from src.personality.thinking_profiler import ThinkingProfiler as _AdvTP
                    thinking_model = _AdvTP.load(
                        components["config"]["paths"].get("thinking_model_file", "data/thinking_model.txt")
                    )
                    return PartnerAdvisor(
                        api_client=client,
                        model=api_cfg.get("model", "gpt-4o-mini"),
                        conversation_builder=components["builder"],
                        parser=components["parser"],
                        cleaner=components["cleaner"],
                        belief_graph=components["belief_graph"],
                        memory_bank=components["memory_bank"],
                        persona_profile=persona_profile,
                        emotion_profile=emo_profile,
                        twin_mode=tw,
                        thinking_model=thinking_model,
                    )

                _advisor_inst = [_init_advisor() if is_ready else None]

                def _get_advisor():
                    if _advisor_inst[0] is None:
                        _advisor_inst[0] = _init_advisor()
                    return _advisor_inst[0]

                _mediator_inst = [None]

                def _init_mediator():
                    adv = _get_advisor()
                    if adv is None:
                        return None
                    return ConflictMediator(
                        api_client=adv.client,
                        model=adv.model,
                        conversation_builder=adv.builder,
                        parser=adv.parser,
                        cleaner=adv.cleaner,
                        belief_graph=adv.belief_graph,
                        memory_bank=adv.memory_bank,
                        persona_profile=adv.persona_profile,
                        emotion_profile=adv.emotion_profile,
                        twin_mode=adv.twin_mode,
                        thinking_model=adv.thinking_model,
                    )

                def _get_mediator():
                    if _mediator_inst[0] is None:
                        _mediator_inst[0] = _init_mediator()
                    return _mediator_inst[0]

                from src.data.partner_config import load_twin_mode as _ltm_chat
                _chat_tw = _ltm_chat()
                _chat_desc = (
                    "TA 的分身，用 TA 的语气跟你对话。"
                    if _chat_tw == "partner"
                    else "你的分身，用你的语气回应。"
                )
                gr.HTML(
                    f'<div style="margin-bottom:12px">'
                    f'<span style="font-size:.85em;color:#8c7b7f">{_chat_desc}</span>'
                    f'</div>'
                )

                with gr.Row():
                    with gr.Column(scale=0, min_width=160, elem_id="sidebar-col"):
                        adv_new_btn = gr.Button("＋ 新对话", variant="primary", size="sm", elem_id="new-chat-btn")
                        adv_session_radio = gr.Radio(
                            choices=[], label=None, show_label=False,
                            elem_id="session-radio", interactive=True,
                        )
                        adv_del_btn = gr.Button("删除当前对话", variant="secondary", size="sm", elem_id="del-session-btn")

                    with gr.Column(scale=3, elem_id="chat-area"):
                        chatbot = gr.Chatbot(
                            height=520,
                            type="messages",
                            show_label=False,
                            show_copy_button=True,
                            elem_id="main-chatbot",
                        )
                        with gr.Row():
                            msg_input = gr.Textbox(
                                placeholder="跟TA聊聊…",
                                show_label=False, scale=8,
                                container=False, lines=1, max_lines=6,
                                elem_id="chat-input",
                            )
                            send_btn = gr.Button("↑", variant="primary", scale=0, min_width=46, elem_id="send-btn")
                        gr.HTML(
                            '<div style="font-size:12px;color:#888;padding:2px 8px 0">'
                            '💡 在消息中任意位置加上 <b style="color:#a78bfa">@KK</b> '
                            '即可召唤情感顾问，例如：<span style="color:#94a3b8">'
                            '「@KK 我们最近老吵架怎么办」</span></div>'
                        )

                def _adv_refresh_radio(selected_id=None):
                    sessions = _adv_mgr.list_sessions()
                    if not sessions:
                        return gr.update(choices=[], value=None)
                    choices = []
                    for s in sessions[:15]:
                        raw = s["title"] or "新对话"
                        title = raw[:13] + "…" if len(raw) > 14 else raw
                        choices.append((title, s["id"]))
                    return gr.update(choices=choices, value=selected_id)

                def _adv_session_to_chatbot(session):
                    if session is None:
                        return []
                    result = []
                    for m in session.messages:
                        content = m["content"]
                        if m["role"] == "assistant" and content.startswith("【KK】"):
                            result.append({"role": "assistant",
                                           "content": f"💜 **KK**：{content[4:].strip()}"})
                        else:
                            result.append({"role": m["role"], "content": content})
                    return result

                def _adv_new_session():
                    s = _adv_mgr.create()
                    radio = _adv_refresh_radio(s.id)
                    return s.id, [], radio

                def _adv_switch_session(choice):
                    if not choice:
                        return gr.update(), []
                    s = _adv_mgr.load(choice)
                    if s is None:
                        return gr.update(), []
                    return s.id, _adv_session_to_chatbot(s)

                def _adv_send(user_msg, session_id, chatbot_history):
                    if not user_msg or not user_msg.strip():
                        return "", chatbot_history, session_id, gr.update()

                    is_xiaoan = "@KK" in user_msg

                    if not session_id:
                        s = _adv_mgr.create()
                        session_id = s.id
                    else:
                        s = _adv_mgr.load(session_id)
                        if s is None:
                            s = _adv_mgr.create()
                            session_id = s.id

                    if is_xiaoan:
                        mediator = _get_mediator()
                        if mediator is None:
                            chatbot_history = chatbot_history or []
                            chatbot_history.append({"role": "assistant",
                                                    "content": "💜 **KK**：系统未初始化，请先完成学习。"})
                            return "", chatbot_history, session_id, gr.update()

                        clean_msg = user_msg.replace("@KK", "").strip() or user_msg.strip()
                        s.add_message("user", user_msg.strip())

                        mediator._ready.wait(timeout=120)
                        system = mediator._system_prompt or "你是 KK，心译的关系洞察顾问。"

                        history = []
                        for m in s.messages[:-1]:
                            c = m["content"]
                            if m["role"] == "assistant" and c.startswith("【KK】"):
                                history.append({"role": "assistant",
                                                "content": c[4:].strip()})
                            elif m["role"] == "assistant":
                                history.append({"role": "user",
                                                "content": f"（对象分身回复了：{c}）"})
                            else:
                                history.append({"role": "user",
                                                "content": c.replace("@KK", "").strip()})
                        history.append({"role": "user", "content": clean_msg})

                        api_messages = [{"role": "system", "content": system}]
                        api_messages.extend(history)

                        try:
                            resp = mediator.client.chat.completions.create(
                                model=mediator.model,
                                messages=api_messages,
                                temperature=0.85,
                                max_tokens=500,
                            )
                            reply = (resp.choices[0].message.content or "").strip()
                        except Exception as e:
                            logger.exception("Mediator LLM call failed")
                            reply = f"不好意思，出了点问题（{e}）"

                        s.add_message("assistant", f"【KK】{reply}")
                    else:
                        advisor = _get_advisor()
                        if advisor is None:
                            chatbot_history = chatbot_history or []
                            chatbot_history.append({"role": "assistant",
                                                    "content": "系统未初始化，请先完成训练。"})
                            return "", chatbot_history, session_id, gr.update()
                        advisor.chat(user_msg.strip(), s)

                    s.auto_title()
                    _adv_mgr.save(s)
                    radio = _adv_refresh_radio(session_id)
                    return "", _adv_session_to_chatbot(s), session_id, radio

                def _adv_delete(session_id):
                    if session_id:
                        _adv_mgr.delete(session_id)
                    radio = _adv_refresh_radio()
                    return None, [], radio

                adv_new_btn.click(
                    fn=_adv_new_session,
                    outputs=[_adv_state, chatbot, adv_session_radio],
                )
                send_btn.click(
                    fn=_adv_send,
                    inputs=[msg_input, _adv_state, chatbot],
                    outputs=[msg_input, chatbot, _adv_state, adv_session_radio],
                )
                msg_input.submit(
                    fn=_adv_send,
                    inputs=[msg_input, _adv_state, chatbot],
                    outputs=[msg_input, chatbot, _adv_state, adv_session_radio],
                )
                adv_session_radio.change(
                    fn=_adv_switch_session,
                    inputs=adv_session_radio,
                    outputs=[_adv_state, chatbot],
                )
                adv_del_btn.click(
                    fn=_adv_delete,
                    inputs=_adv_state,
                    outputs=[_adv_state, chatbot, adv_session_radio],
                )
                demo.load(
                    fn=lambda: _adv_refresh_radio(),
                    outputs=[adv_session_radio],
                )

            # ================================================================
            # Tab: Twin Evaluation
            # ================================================================
            with gr.Tab("关系报告", id="tab-eval", visible=is_ready) as tab_eval:

                # ── Relationship Insights Report ─────────────────────
                gr.Markdown("### 关系全景报告\n基于真实聊天记录，生成多维度关系分析报告。包含情感健康评分、依恋风格、沟通密码、信念图谱。")
                report_btn = gr.Button("生成关系全景报告", variant="primary")
                report_html = gr.HTML()

                def _generate_relationship_report():
                    if components is None:
                        return "<p style='color:red'>系统未初始化，请先完成训练</p>"
                    try:
                        import datetime as _dt
                        cfg = components["config"]

                        # ── Load all data ──────────────────────────────
                        persona_path = Path(cfg["paths"]["persona_file"])
                        persona = {}
                        if persona_path.exists():
                            import yaml as _rpt_yaml
                            with open(persona_path, encoding="utf-8") as f:
                                persona = _rpt_yaml.safe_load(f) or {}

                        from src.personality.emotion_analyzer import EmotionAnalyzer as _RptEA
                        emo_path = cfg["paths"].get("emotion_file", "data/emotion_profile.yaml")
                        emo = _RptEA.load(emo_path) or {}

                        digest_path = Path("data/mediation_digest.json")
                        digest = ""
                        if digest_path.exists():
                            try:
                                d = json.loads(digest_path.read_text(encoding="utf-8"))
                                digest = d.get("digest", "")
                            except Exception:
                                pass

                        beliefs_path = Path(cfg["paths"].get("beliefs_file", "data/beliefs.json"))
                        beliefs_raw = {}
                        if beliefs_path.exists():
                            try:
                                rb = json.loads(beliefs_path.read_text(encoding="utf-8"))
                                beliefs_raw = rb.get("beliefs", rb) if isinstance(rb, dict) else {}
                            except Exception:
                                pass

                        thinking_path = Path(cfg["paths"].get("thinking_model_file", "data/thinking_model.txt"))
                        thinking_text = ""
                        if thinking_path.exists():
                            try:
                                thinking_text = thinking_path.read_text(encoding="utf-8")[:4000]
                            except Exception:
                                pass

                        # ── Extract fields ─────────────────────────────
                        basic = persona.get("basic_info", {})
                        name = basic.get("name", basic.get("姓名", "TA"))
                        gender = basic.get("gender", basic.get("性别", ""))
                        age = basic.get("age", basic.get("年龄", ""))
                        location = basic.get("location", basic.get("所在地", ""))
                        total_msgs = persona.get("total_messages_analyzed", 0)
                        avg_len = persona.get("avg_message_length", 0)
                        avg_resp = persona.get("avg_response_time_seconds", 0)
                        emoji_freq = persona.get("emoji_frequency", 0)
                        vocab_rich = persona.get("vocabulary_richness", 0)
                        msg_dist = persona.get("message_length_distribution", {})
                        catchphrases = persona.get("vocab_bank", {}).get("catchphrases", [])[:10]
                        slang = persona.get("vocab_bank", {}).get("slang", [])[:8]
                        top_phrases = [(p[0], p[1]) for p in (persona.get("top_phrases") or [])[:12] if isinstance(p, (list, tuple)) and len(p) == 2]

                        emo_dist = emo.get("emotion_distribution", {})
                        emo_triggers = emo.get("emotion_triggers", emo.get("triggers", {}))
                        emo_transitions = emo.get("emotion_transitions", {})

                        # ── Metric computations ────────────────────────
                        # Remove neutral for ratio calculations
                        active_emo = {k: v for k, v in emo_dist.items() if k != "neutral"}
                        total_active = max(sum(active_emo.values()), 1)

                        POS_KEYS = {"joy", "coquettish", "gratitude", "pride", "touched", "excitement"}
                        NEG_KEYS = {"anger", "anxiety", "disappointment", "sadness", "wronged", "heartache", "jealousy"}
                        pos_sum = sum(v for k, v in active_emo.items() if k in POS_KEYS)
                        neg_sum = sum(v for k, v in active_emo.items() if k in NEG_KEYS)
                        pos_ratio = pos_sum / total_active
                        neg_ratio = neg_sum / total_active
                        # Gottman magic ratio benchmark is 5:1
                        magic_ratio = pos_sum / max(neg_sum, 1)

                        # Emotion repair speed: transitions back to neutral / total transitions
                        to_neutral = sum(v for k, v in emo_transitions.items() if k.endswith("->neutral"))
                        total_transitions = max(sum(emo_transitions.values()), 1)
                        repair_rate = to_neutral / total_transitions

                        # 5 Gottman-inspired dimensions (0–100)
                        # 1. Emotional connection: positive emo density
                        d_connection = min(100, round(pos_ratio * 140))
                        # 2. Conflict health: penalize high anger/contempt ratio
                        anger_v = active_emo.get("anger", 0)
                        wronged_v = active_emo.get("wronged", 0)
                        d_conflict = max(0, round(100 - (anger_v + wronged_v) / total_active * 300))
                        # 3. Trust & security: penalize anxiety + jealousy
                        anx_v = active_emo.get("anxiety", 0)
                        jeal_v = active_emo.get("jealousy", 0)
                        d_trust = max(0, round(100 - (anx_v + jeal_v) / total_active * 200))
                        # 4. Communication vitality: avg_len, emoji_freq, response_time
                        resp_score = max(0, 100 - min(avg_resp, 600) / 6)
                        len_score = min(100, avg_len / 15 * 100)
                        d_comm = round((resp_score * 0.5 + len_score * 0.3 + emoji_freq * 2000 * 0.2))
                        d_comm = min(100, max(0, d_comm))
                        # 5. Emotional resilience: repair rate
                        d_resilience = min(100, round(repair_rate * 160))

                        def score_color(s):
                            if s >= 75: return "#65a88a"
                            if s >= 50: return "#fbbf24"
                            return "#f87171"

                        def score_label(s):
                            if s >= 80: return "优秀"
                            if s >= 65: return "良好"
                            if s >= 45: return "一般"
                            return "需关注"

                        # ── Infer attachment style ─────────────────────
                        anx_pct = anx_v / total_active
                        longing_v = active_emo.get("longing", 0)
                        # Anxious markers: high anxiety, longing, low trust score, "分离焦虑" in thinking
                        anxious_score = anx_pct * 3 + (longing_v / total_active) + (1 if "分离焦虑" in thinking_text else 0) + (1 if "先试探安全性" in thinking_text else 0)
                        # Avoidant markers: low coquettish, "切断式" patterns
                        coquettish_pct = active_emo.get("coquettish", 0) / total_active
                        avoidant_score = (0.3 - coquettish_pct) + (1 if "切断式" in thinking_text else 0) + (1 if "收回互动权限" in thinking_text else 0)
                        # Secure markers: high repair rate, positive ratio
                        secure_score = repair_rate * 2 + pos_ratio

                        if anxious_score > avoidant_score and anxious_score > secure_score:
                            attach_type = "焦虑型依恋"
                            attach_icon = "🔍"
                            attach_color = "#fb923c"
                            attach_desc = "在关系中倾向于主动确认，回应慢时容易激活『我是否被在乎』的警报系统。需要持续的安全信号，一旦被接住就能迅速软化并恢复合作。"
                        elif avoidant_score > anxious_score and avoidant_score > secure_score:
                            attach_type = "回避型依恋"
                            attach_icon = "🛡️"
                            attach_color = "#60a5fa"
                            attach_desc = "在亲密关系中保持情感距离以维护安全感。遇到压力时更可能用切断式回应来保护自己，但内心有真实的依恋需求。"
                        else:
                            attach_type = "安全型依恋（倾向）"
                            attach_icon = "⚡"
                            attach_color = "#65a88a"
                            attach_desc = "基本能在情绪激活后较快恢复，修复意愿强，在冲突后能重新回到合作状态。关系稳定性相对较高。"

                        # ── Beliefs: pick high-confidence, varied topics ──
                        belief_list = []
                        if isinstance(beliefs_raw, dict):
                            for b in beliefs_raw.values():
                                if isinstance(b, dict) and b.get("confidence", 0) >= 0.85:
                                    belief_list.append(b)
                        belief_list.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                        seen_topics = set()
                        deduped_beliefs = []
                        for b in belief_list:
                            topic = b.get("topic", "")
                            if topic not in seen_topics:
                                seen_topics.add(topic)
                                deduped_beliefs.append(b)
                            if len(deduped_beliefs) >= 6:
                                break

                        # ── Emotion map: top non-neutral emotions ─────
                        emo_map_colors = {
                            "joy": "#fbbf24", "coquettish": "#f472b6", "gratitude": "#34d399",
                            "pride": "#a78bfa", "touched": "#f9a8d4", "excitement": "#fb923c",
                            "longing": "#818cf8", "curiosity": "#60a5fa",
                            "anger": "#ef4444", "anxiety": "#fb923c", "disappointment": "#a8969a",
                            "sadness": "#818cf8", "wronged": "#c084fc", "heartache": "#f87171",
                            "jealousy": "#e879f9",
                        }
                        emo_label_map = {
                            "joy": "开心", "coquettish": "撒娇", "gratitude": "感激",
                            "pride": "自豪", "touched": "感动", "excitement": "兴奋",
                            "longing": "思念", "curiosity": "好奇",
                            "anger": "愤怒", "anxiety": "焦虑", "disappointment": "失望",
                            "sadness": "悲伤", "wronged": "委屈", "heartache": "心痛",
                            "jealousy": "嫉妒",
                        }
                        sorted_active = sorted(active_emo.items(), key=lambda x: x[1], reverse=True)[:10]
                        max_emo_val = max((v for _, v in sorted_active), default=1)

                        today = _dt.date.today().strftime("%Y年%m月%d日")

                        # ════════════════════════════════════════════════
                        # HTML BUILD — desktop-first grid layout
                        # ════════════════════════════════════════════════

                        def section(title, icon, color, body):
                            return f"""<div style="background:#2a2225;border-radius:14px;padding:20px 22px;height:100%;box-sizing:border-box">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #ffffff0d">
    <span style="font-size:16px">{icon}</span>
    <span style="font-size:13px;font-weight:700;color:{color};letter-spacing:.05em;text-transform:uppercase">{title}</span>
  </div>
  {body}
</div>"""

                        def metric_row(label, val, color, note=""):
                            note_html = f"<span style='color:#5a4d50;font-size:11px;margin-left:6px'>{note}</span>" if note else ""
                            return (
                                f"<div style='display:flex;align-items:center;margin-bottom:12px'>"
                                f"<span style='width:110px;font-size:12px;color:#a8969a;flex-shrink:0'>{label}</span>"
                                f"<div style='flex:1;height:8px;background:#1e181b;border-radius:4px;overflow:hidden'>"
                                f"<div style='width:{val}%;height:100%;background:{color};border-radius:4px'></div>"
                                f"</div>"
                                f"<span style='width:36px;text-align:right;font-size:12px;color:{color};margin-left:8px'>{val}</span>"
                                f"{note_html}"
                                f"</div>"
                            )

                        def stat_box(label, value, sub=""):
                            sub_html = ("<div style='font-size:10px;color:#5a4d50;margin-top:2px'>"
                                        + sub + "</div>") if sub else ""
                            return (
                                f"<div style='background:#1e181b;border-radius:10px;padding:14px 16px;text-align:center'>"
                                f"<div style='font-size:22px;font-weight:700;color:#f0e8e4'>{value}</div>"
                                f"<div style='font-size:11px;color:#7a6b6f;margin-top:3px'>{label}</div>"
                                f"{sub_html}"
                                f"</div>"
                            )

                        def tag(text, color="#a8969a"):
                            return (
                                f"<span style='display:inline-block;padding:4px 10px;border-radius:6px;"
                                f"background:{color}18;color:{color};border:1px solid {color}30;"
                                f"font-size:12px;margin:3px'>{text}</span>"
                            )

                        # Section 1: 基础数据速写
                        stat_row = (
                            f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px'>"
                            f"{stat_box('消息总量', f'{total_msgs:,}' if total_msgs else '—', '已分析')}"
                            f"{stat_box('平均字数', f'{avg_len:.1f}', '字/条')}"
                            f"{stat_box('平均回复', f'{int(avg_resp//60)}m{int(avg_resp%60)}s' if avg_resp else '—', '响应时间')}"
                            f"{stat_box('词汇丰富度', f'{vocab_rich:.1%}' if vocab_rich else '—', '类型/词元比')}"
                            f"</div>"
                        )
                        msg_dist_html = ""
                        if msg_dist:
                            for lbl, pct in [("短消息(≤10字)", msg_dist.get("short", 0)), ("中消息", msg_dist.get("medium", 0)), ("长消息(>50字)", msg_dist.get("long", 0))]:
                                c = "#60a5fa" if "短" in lbl else "#a78bfa" if "中" in lbl else "#f472b6"
                                msg_dist_html += metric_row(lbl, min(100, int(pct)), c)
                        sec1_body = stat_row + msg_dist_html
                        if catchphrases:
                            sec1_body += f"<div style='margin-top:12px'><span style='font-size:11px;color:#5a4d50;display:block;margin-bottom:6px'>口头禅</span>"
                            sec1_body += "".join(tag(p, "#818cf8") for p in catchphrases[:8])
                            sec1_body += "</div>"
                        sec1 = section("沟通速写", "📊", "#60a5fa", sec1_body)

                        # Section 2: 情感色谱
                        emo_bars_html = ""
                        for emo_key, emo_val in sorted_active:
                            pct = round(emo_val / max_emo_val * 100)
                            c = emo_map_colors.get(emo_key, "#a8969a")
                            lbl = emo_label_map.get(emo_key, emo_key)
                            raw_pct = round(emo_val / total_active * 100)
                            emo_bars_html += (
                                f"<div style='display:flex;align-items:center;margin-bottom:8px'>"
                                f"<span style='width:44px;font-size:12px;color:#a8969a;flex-shrink:0;text-align:right;margin-right:10px'>{lbl}</span>"
                                f"<div style='flex:1;height:16px;background:#1e181b;border-radius:8px;overflow:hidden'>"
                                f"<div style='width:{pct}%;height:100%;background:linear-gradient(90deg,{c}66,{c});border-radius:8px'></div>"
                                f"</div>"
                                f"<span style='width:32px;font-size:11px;color:#7a6b6f;margin-left:8px;text-align:right'>{raw_pct}%</span>"
                                f"</div>"
                            )
                        # positive/negative summary
                        ratio_label = f"正负情绪比 {pos_sum}:{neg_sum} ≈ {magic_ratio:.1f}:1"
                        ratio_color = "#65a88a" if magic_ratio >= 5 else "#fbbf24" if magic_ratio >= 2 else "#f87171"
                        emo_bars_html += (
                            f"<div style='margin-top:14px;padding:10px 14px;background:#1e181b;"
                            f"border-radius:8px;font-size:12px;color:{ratio_color}'>"
                            f"Gottman 黄金比例基准 5:1 ·&nbsp;<b>{ratio_label}</b>"
                            f"</div>"
                        )
                        sec2 = section("情感色谱", "🌈", "#fbbf24", emo_bars_html)

                        # Section 3: 5 dimensions
                        dims = [
                            ("情感联结", d_connection, "与伴侣的亲密感、积极情绪密度"),
                            ("冲突健康", d_conflict, "愤怒/委屈占比，越高越健康"),
                            ("信任安全感", d_trust, "焦虑/嫉妒占比，越高越稳定"),
                            ("沟通活跃度", d_comm, "响应速度、消息长度综合"),
                            ("情绪恢复力", d_resilience, "从负面情绪回到平静的速度"),
                        ]
                        dims_html = ""
                        for dim_name, dim_val, dim_desc in dims:
                            c = score_color(dim_val)
                            lbl = score_label(dim_val)
                            dims_html += (
                                f"<div style='margin-bottom:14px'>"
                                f"<div style='display:flex;justify-content:space-between;margin-bottom:5px'>"
                                f"<span style='font-size:13px;color:#e6dcd8'>{dim_name}</span>"
                                f"<span style='font-size:12px;color:{c};font-weight:600'>{dim_val} · {lbl}</span>"
                                f"</div>"
                                f"<div style='height:8px;background:#1e181b;border-radius:4px;overflow:hidden;margin-bottom:4px'>"
                                f"<div style='width:{dim_val}%;height:100%;background:linear-gradient(90deg,{c}66,{c});border-radius:4px'></div>"
                                f"</div>"
                                f"<div style='font-size:11px;color:#5a4d50'>{dim_desc}</div>"
                                f"</div>"
                            )
                        sec3 = section("关系健康五维度", "💎", "#a78bfa", dims_html)

                        # Section 4: 依恋风格
                        attach_html = (
                            f"<div style='text-align:center;padding:16px 0 20px'>"
                            f"<div style='font-size:32px;margin-bottom:8px'>{attach_icon}</div>"
                            f"<div style='font-size:18px;font-weight:700;color:{attach_color}'>{attach_type}</div>"
                            f"</div>"
                            f"<div style='font-size:13px;color:#a8969a;line-height:1.8;padding:14px;background:#1e181b;border-radius:10px'>"
                            f"{attach_desc}</div>"
                        )
                        if thinking_text:
                            # Extract first 2 reaction patterns from thinking model
                            lines = [l.strip() for l in thinking_text.split("\n") if l.strip() and "→" in l][:3]
                            if lines:
                                attach_html += "<div style='margin-top:14px'><span style='font-size:11px;color:#5a4d50;display:block;margin-bottom:8px'>典型反应模式（来自思维建模）</span>"
                                for line in lines:
                                    parts = line.split("→")
                                    if len(parts) == 2:
                                        trigger_txt = parts[0].lstrip("0123456789). ").strip()
                                        react_txt = parts[1].strip()
                                        attach_html += (
                                            f"<div style='padding:8px 12px;background:#1e2a25;border-radius:8px;"
                                            f"margin-bottom:6px;font-size:12px'>"
                                            f"<span style='color:#7a6b6f'>触发：</span><span style='color:#a8969a'>{trigger_txt[:40]}</span>"
                                            f"<br><span style='color:#7a6b6f'>反应：</span><span style='color:#65a88a'>{react_txt[:60]}</span>"
                                            f"</div>"
                                        )
                                attach_html += "</div>"
                        sec4 = section("依恋风格分析", "🔗", attach_color, attach_html)

                        # Section 5: 关系动力摘要 (full width)
                        digest_section = ""
                        if digest:
                            digest_lines_html = ""
                            for line in digest.split("\n"):
                                line = line.strip()
                                if not line:
                                    continue
                                if line.startswith("- **") or line.startswith("**"):
                                    # Bold heading line
                                    import re as _re
                                    line_html = _re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#f0e8e4'>\1</b>", line.lstrip("- "))
                                    digest_lines_html += f"<div style='margin-bottom:8px;padding:10px 14px;background:#1e181b;border-radius:8px;font-size:13px;color:#a8969a;line-height:1.7'>{line_html}</div>"
                                else:
                                    digest_lines_html += f"<div style='font-size:13px;color:#a8969a;line-height:1.7;margin-bottom:6px'>{line}</div>"
                            digest_section = section("关系动力摘要", "🔬", "#f472b6",
                                f"<div style='columns:2;gap:16px'>{digest_lines_html}</div>")

                        # Section 6: 核心信念
                        beliefs_html = ""
                        for b in deduped_beliefs:
                            conf = b.get("confidence", 0)
                            topic = b.get("topic", "")
                            stance = b.get("stance", "")
                            conf_c = "#65a88a" if conf >= 0.9 else "#fbbf24" if conf >= 0.75 else "#a8969a"
                            beliefs_html += (
                                f"<div style='padding:12px 14px;background:#1e181b;border-radius:10px;"
                                f"margin-bottom:8px;border-left:3px solid {conf_c}44'>"
                                f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
                                f"<span style='font-size:11px;color:#7a6b6f;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>{topic}</span>"
                                f"<span style='font-size:11px;color:{conf_c}'>置信度 {conf:.0%}</span>"
                                f"</div>"
                                f"<div style='font-size:13px;color:#e6dcd8;line-height:1.6'>{stance}</div>"
                                f"</div>"
                            )
                        sec6 = section("核心信念图谱", "🧠", "#c084fc", beliefs_html or "<p style='color:#5a4d50'>暂无信念数据</p>")

                        # Section 7: 情绪触发地图
                        trigger_html = ""
                        trigger_groups = [
                            ("anger", "愤怒", "#ef4444"),
                            ("anxiety", "焦虑", "#fb923c"),
                            ("wronged", "委屈", "#a78bfa"),
                            ("sadness", "悲伤", "#818cf8"),
                            ("disappointment", "失望", "#7a6b6f"),
                        ]
                        for tkey, tlabel, tcolor in trigger_groups:
                            words = []
                            tr_info = emo_triggers.get(tkey, [])
                            if isinstance(tr_info, list):
                                words = [w for w in tr_info if isinstance(w, str)][:6]
                            elif isinstance(tr_info, dict):
                                words = tr_info.get("top_words", [])[:6]
                            if not words:
                                continue
                            trigger_html += (
                                f"<div style='margin-bottom:12px'>"
                                f"<span style='font-size:12px;font-weight:600;color:{tcolor};display:block;margin-bottom:6px'>{tlabel}</span>"
                                f"{''.join(tag(w, tcolor) for w in words)}"
                                f"</div>"
                            )
                        sec7 = section("情绪触发地图", "⚡", "#f87171", trigger_html or "<p style='color:#5a4d50'>暂无触发数据</p>")

                        # ── Assemble final HTML ─────────────────────────
                        html = f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;
  color:#f0e8e4;background:#1e181b;padding:28px;border-radius:16px;min-width:700px">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:24px;
    padding-bottom:18px;border-bottom:1px solid #2a2225">
    <div>
      <div style="font-size:22px;font-weight:800;background:linear-gradient(135deg,#c084fc,#f472b6,#fb923c);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px">
        {name} 的关系全景报告</div>
      <div style="font-size:13px;color:#5a4d50">
        {gender}{('·' + age + '岁') if age else ''}{('·' + location) if location else ''}
        &nbsp;·&nbsp;基于 {total_msgs:,} 条真实消息 &nbsp;·&nbsp; {today}
      </div>
    </div>
    <div style="font-size:11px;color:#5a4d50;text-align:right">心译 · AI 关系洞察<br>Gottman / EFT 框架</div>
  </div>

  <!-- Row 1: stats + emotion spectrum -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
    {sec1}
    {sec2}
  </div>

  <!-- Row 2: 5 dimensions + attachment -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
    {sec3}
    {sec4}
  </div>

  <!-- Row 3: relationship dynamics (full width) -->
  {"<div style='margin-bottom:14px'>" + digest_section + "</div>" if digest_section else ""}

  <!-- Row 4: beliefs + triggers -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
    {sec6}
    {sec7}
  </div>

</div>"""
                        return html

                    except Exception as e:
                        logger.exception("Report generation failed")
                        return f"<p style='color:red'>报告生成失败: {e}</p>"

                report_btn.click(fn=_generate_relationship_report, outputs=report_html)

                gr.Markdown("---")

                gr.Markdown(
                    "### 分身诊断\n"
                    "通过向分身提问，评估它对你思维模式的还原程度，并给出是否需要继续校准的建议。"
                )
                diag_btn = gr.Button("开始诊断", variant="primary")
                diag_result_html = gr.HTML()

                def run_twin_diagnosis():
                    if components is None:
                        return "<p style='color:red'>系统未初始化</p>"
                    try:
                        import openai as _oai
                        from src.data.partner_config import load_twin_mode as _ltm_diag

                        c = components
                        _tw_mode = _ltm_diag()
                        engine = c["chat_engine"]

                        # ── 1. 思维模式探针问题 ──────────────────────────────
                        thinking_probes = [
                            ("决策偏好", "你需要在两件同样重要的事里选一件，你会怎么决定？"),
                            ("冲突处理", "如果身边的人做了让你不舒服的事，你第一反应会怎么做？"),
                            ("不确定感", "面对一件完全没把握的事，你会先动手还是先想清楚再说？"),
                            ("情绪表达", "你难过的时候，更倾向于自己消化还是说出来？"),
                            ("价值排序", "工作和休息之间，你怎么给自己划边界？"),
                        ]
                        tone_probes = [
                            ("语气温度", "今天过得怎么样？"),
                            ("回应长度", "随便聊一件最近让你开心的小事。"),
                        ]

                        thinking_replies: list[tuple[str, str, str]] = []
                        tone_replies: list[tuple[str, str, str]] = []

                        def _ask(question: str) -> str:
                            try:
                                resp = engine.chat(question)
                                return (resp or "").strip()
                            except Exception:
                                return ""

                        for dim, q in thinking_probes:
                            thinking_replies.append((dim, q, _ask(q)))
                        for dim, q in tone_probes:
                            tone_replies.append((dim, q, _ask(q)))

                        # ── 2. 构造 LLM 评估 prompt ──────────────────────────
                        qa_block = "\n".join(
                            f"[{dim}] 问：{q}\n分身答：{a if a else '（无回复）'}"
                            for dim, q, a in thinking_replies + tone_replies
                        )

                        profile_hint = ""
                        pb = c.get("prompt_builder")
                        if pb and hasattr(pb, "profile") and pb.profile:
                            p = pb.profile
                            profile_hint = (
                                f"已知真人画像摘要：性格={p.get('personality','未知')}，"
                                f"价值观={p.get('values','未知')}，"
                                f"沟通风格={p.get('communication_style','未知')}\n\n"
                            )

                        eval_prompt = f"""{profile_hint}以下是对数字分身进行诊断的问答记录。
请从两个维度评估：
1. 思维模式还原度（主要）：决策逻辑、冲突处理方式、不确定性应对、情绪模式、价值排序是否符合真人特征。满分100分，权重70%。
2. 语气一致性（次要）：回复温度、表达方式是否接近真人风格。满分100分，权重30%。

问答记录：
{qa_block}

请用以下 JSON 格式输出，不要输出任何多余内容：
{{
  "thinking_score": <0-100整数>,
  "tone_score": <0-100整数>,
  "thinking_issues": ["<问题1>", "<问题2>"],
  "tone_issues": ["<问题1>"],
  "suggestions": ["<具体优化建议1>", "<具体优化建议2>", "<具体优化建议3>"],
  "calibration_needed": <true|false>,
  "calibration_reason": "<一句话说明是否需要继续校准>"
}}"""

                        cfg = c.get("config", {}) or {}
                        api_cfg = cfg.get("api", {}) or {}
                        api_base = api_cfg.get("base_url") or "https://api.openai.com/v1"
                        api_key = api_cfg.get("api_key", "")
                        model = api_cfg.get("model", "gpt-4o")
                        extra_headers = api_cfg.get("headers", {})

                        _cli = _oai.OpenAI(api_key=api_key, base_url=api_base, default_headers=extra_headers)
                        raw_eval = (_cli.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": eval_prompt}],
                            temperature=0.2,
                        ).choices[0].message.content or "").strip()

                        import json as _json
                        import re as _re_diag
                        _m = _re_diag.search(r'\{[\s\S]+\}', raw_eval)
                        ev = _json.loads(_m.group()) if _m else {}

                        thinking_score = int(ev.get("thinking_score", 0))
                        tone_score = int(ev.get("tone_score", 0))
                        overall = round(thinking_score * 0.7 + tone_score * 0.3)
                        calibration_needed = ev.get("calibration_needed", False)
                        calibration_reason = ev.get("calibration_reason", "")
                        suggestions = ev.get("suggestions", [])
                        thinking_issues = ev.get("thinking_issues", [])
                        tone_issues = ev.get("tone_issues", [])

                        def _score_color(s):
                            if s >= 75: return "#65a88a"
                            if s >= 50: return "#f59e0b"
                            return "#ef4444"

                        def _bar(s):
                            color = _score_color(s)
                            return (
                                f"<div style='background:#3a3035;border-radius:4px;height:8px;margin:4px 0'>"
                                f"<div style='background:{color};width:{s}%;height:8px;border-radius:4px;transition:width .4s'></div></div>"
                            )

                        issues_html = ""
                        if thinking_issues:
                            issues_html += "<div style='margin-top:6px;font-size:.85em;color:#c0a8b0'>"
                            for iss in thinking_issues:
                                issues_html += f"<span style='margin-right:8px'>· {iss}</span>"
                            issues_html += "</div>"

                        tone_issues_html = ""
                        if tone_issues:
                            tone_issues_html += "<div style='margin-top:4px;font-size:.85em;color:#c0a8b0'>"
                            for iss in tone_issues:
                                tone_issues_html += f"<span style='margin-right:8px'>· {iss}</span>"
                            tone_issues_html += "</div>"

                        sug_html = "".join(
                            f"<li style='margin:6px 0;color:#d4c4c8'>{s}</li>"
                            for s in suggestions
                        )

                        calib_color = "#ef4444" if calibration_needed else "#65a88a"
                        calib_icon = "⚠️ 建议继续校准" if calibration_needed else "✓ 暂时不需要校准"

                        html = f"""<div style='font-family:var(--font);padding:20px;background:#1e181b;border-radius:12px;color:#e0d4d8'>

  <div style='display:flex;align-items:center;gap:16px;margin-bottom:20px'>
    <div style='text-align:center;background:#2a2225;padding:14px 20px;border-radius:10px;min-width:80px'>
      <div style='font-size:2em;font-weight:700;color:{_score_color(overall)}'>{overall}</div>
      <div style='font-size:.75em;color:#a8969a;margin-top:2px'>综合评分</div>
    </div>
    <div style='flex:1'>
      <div style='font-size:.85em;color:#a8969a;margin-bottom:4px'>思维模式还原度 <span style='color:{_score_color(thinking_score)};font-weight:600'>{thinking_score}/100</span></div>
      {_bar(thinking_score)}
      {issues_html}
      <div style='font-size:.85em;color:#a8969a;margin-top:10px;margin-bottom:4px'>语气一致性 <span style='color:{_score_color(tone_score)};font-weight:600'>{tone_score}/100</span></div>
      {_bar(tone_score)}
      {tone_issues_html}
    </div>
  </div>

  <div style='background:#2a2225;border-radius:8px;padding:14px;margin-bottom:14px'>
    <div style='font-size:.85em;color:#a8969a;margin-bottom:8px;font-weight:600'>优化建议</div>
    <ul style='margin:0;padding-left:18px;line-height:1.8'>{sug_html}</ul>
  </div>

  <div style='border:1px solid {calib_color}33;border-radius:8px;padding:12px 16px;display:flex;align-items:flex-start;gap:10px'>
    <span style='color:{calib_color};font-size:1em;white-space:nowrap'>{calib_icon}</span>
    <span style='font-size:.9em;color:#d4c4c8;line-height:1.6'>{calibration_reason}</span>
  </div>

</div>"""
                        return html

                    except Exception as e:
                        logger.exception("Twin diagnosis failed")
                        return f"<p style='color:red'>诊断失败: {e}</p>"

                diag_btn.click(fn=run_twin_diagnosis, outputs=diag_result_html)


            # ================================================================
            # Tab: Personality Calibration (人格校准)
            # ================================================================
            with gr.Tab("校准", id="tab-cognitive", visible=is_ready) as tab_cognitive:
                gr.Markdown(
                    "### 人格校准\n"
                    "通过情境任务校准分身的认知模型。\n"
                    "这些不是问卷，而是有约束的情境——**没有标准答案，你怎么想就怎么说**。\n"
                    "系统会从你的选择中反推你的思维逻辑，而不是相信自述。\n\n"
                    "做得越多，心译越懂你。学习完成即可使用对话功能。"
                )

                with gr.Accordion("基本信息（让数字分身知道自己是谁）", open=True):
                    with gr.Row():
                        bi_name = gr.Textbox(label="姓名", placeholder="真实姓名")
                        bi_nickname = gr.Textbox(label="昵称", placeholder="朋友怎么叫你")
                    with gr.Row():
                        bi_gender = gr.Dropdown(label="性别", choices=["男", "女", "其他"], value=None, allow_custom_value=True)
                        bi_age = gr.Textbox(label="年龄/年龄段", placeholder="如 23 或 20出头")
                    with gr.Row():
                        bi_location = gr.Textbox(label="所在城市", placeholder="如 深圳")
                        bi_occupation = gr.Textbox(label="职业/身份", placeholder="如 大学生、程序员")
                    bi_extra = gr.Textbox(label="其他补充", placeholder="任何你想让数字分身记住的身份信息", lines=2)
                    bi_save_btn = gr.Button("保存基本信息", variant="primary")
                    bi_status = gr.HTML(value="")

                    def _load_basic_info():
                        if not components or not components.get("config"):
                            return "", "", None, "", "", "", ""
                        p = Path(components["config"]["paths"]["persona_file"])
                        if not p.exists():
                            return "", "", None, "", "", "", ""
                        import yaml as _yaml
                        with open(p, encoding="utf-8") as f:
                            prof = _yaml.safe_load(f) or {}
                        bi = prof.get("basic_info", {})
                        return (
                            bi.get("name", ""), bi.get("nickname", ""),
                            bi.get("gender"), bi.get("age", ""),
                            bi.get("location", ""), bi.get("occupation", ""),
                            bi.get("extra", ""),
                        )

                    def _save_basic_info(name, nickname, gender, age, location, occupation, extra):
                        if not components or not components.get("config"):
                            return "<span style='color:#ef4444'>系统未初始化</span>"
                        import yaml as _yaml
                        p = Path(components["config"]["paths"]["persona_file"])
                        prof = {}
                        if p.exists():
                            with open(p, encoding="utf-8") as f:
                                prof = _yaml.safe_load(f) or {}
                        bi = {}
                        if name.strip(): bi["name"] = name.strip()
                        if nickname.strip(): bi["nickname"] = nickname.strip()
                        if gender: bi["gender"] = gender
                        if age.strip(): bi["age"] = age.strip()
                        if location.strip(): bi["location"] = location.strip()
                        if occupation.strip(): bi["occupation"] = occupation.strip()
                        if extra.strip(): bi["extra"] = extra.strip()
                        prof["basic_info"] = bi
                        with open(p, "w", encoding="utf-8") as f:
                            _yaml.dump(prof, f, allow_unicode=True, default_flow_style=False)

                        if components.get("prompt_builder"):
                            components["prompt_builder"].profile = prof
                            components["prompt_builder"].regenerate_guidance()

                        filled = [v for v in bi.values() if v]
                        return f"<span style='color:#10b981'>✓ 已保存 {len(filled)} 项基本信息，identity.md 已更新</span>"

                    bi_save_btn.click(
                        fn=_save_basic_info,
                        inputs=[bi_name, bi_nickname, bi_gender, bi_age, bi_location, bi_occupation, bi_extra],
                        outputs=[bi_status],
                    )
                    demo.load(
                        fn=_load_basic_info,
                        outputs=[bi_name, bi_nickname, bi_gender, bi_age, bi_location, bi_occupation, bi_extra],
                    )
                task_progress_html = gr.HTML(value="")
                with gr.Group():
                    task_display = gr.Markdown(value="*点击「开始校准」获取第一道题*")
                    task_response = gr.Textbox(
                        label="你的回答",
                        placeholder="认真想，不需要标准答案。你平时怎么做就怎么说。",
                        lines=5,
                    )
                    with gr.Row():
                        next_task_btn = gr.Button("开始校准", variant="primary", scale=2)
                        submit_task_btn = gr.Button("提交并下一题", variant="secondary", scale=2)
                task_current_id = gr.State(value="")
                task_current_prompt = gr.State(value="")
                task_analysis_output = gr.Markdown(value="")

                with gr.Accordion("矛盾检测（校准完成后可用）", open=False):
                    scan_contradictions_btn = gr.Button("扫描信念矛盾", variant="secondary")
                    contradiction_output = gr.Markdown(value="")

                def _task_progress_html():
                    if components is None:
                        return ""
                    tl = components.get("task_library")
                    if not tl:
                        return ""
                    done = tl.get_completed_count()
                    total = tl.get_total_count()
                    pct = int(done / max(total, 1) * 100) if total else 0
                    pct = min(pct, 100)
                    bar_color = "#10b981" if done > 0 else "#f59e0b"
                    status_text = f"已完成 {done} 题" if done > 0 else "尚未开始"
                    return (
                        f"<div style='padding:12px 16px;background:#2a2225;border-radius:10px;'>"
                        f"<div style='display:flex;justify-content:space-between;margin-bottom:6px;'>"
                        f"<span>已完成 <b>{done}</b>/{total} 题</span>"
                        f"<span style='color:{bar_color};font-weight:600'>{status_text}</span></div>"
                        f"<div style='background:#5a4d50;border-radius:4px;height:8px;'>"
                        f"<div style='background:{bar_color};height:8px;border-radius:4px;"
                        f"width:{pct}%;transition:width .3s'></div>"
                        f"</div></div>"
                    )

                def _next_task():
                    if components is None:
                        return "系统未初始化", "", "", _task_progress_html()
                    tl = components.get("task_library")
                    if not tl:
                        return "任务库未加载", "", "", ""
                    task = tl.get_next_task()
                    if not task:
                        return "**校准完成！** 所有任务已做完。可以去「心译对话」开始了。", "", "", _task_progress_html()
                    done = tl.get_completed_count()
                    num = done + 1
                    dim_name = TASK_DIMENSIONS.get(task["dimension"], task["dimension"])
                    md = f"### 第 {num} 题 · {dim_name}\n\n{task['prompt']}"
                    return md, task["id"], task["prompt"], _task_progress_html()

                def _submit_task(task_id, task_prompt, response_text):
                    if not task_id or not response_text.strip():
                        return "请先获取任务并填写回答", _task_progress_html(), gr.update(), "", "", gr.update()
                    if components is None:
                        return "系统未初始化", "", gr.update(), "", "", gr.update()
                    tl = components["task_library"]
                    ie = components["inference_engine"]
                    bg = components["belief_graph"]
                    cd = components["contradiction_detector"]

                    task_result = tl.record_response(task_id, response_text, task_prompt)
                    analysis = ie.analyze_response(task_result)

                    new_beliefs_added = 0
                    if analysis:
                        for b in analysis.get("inferred_beliefs", []):
                            if not b.get("topic"):
                                continue
                            b["source"] = f"task_{task_id}"
                            bid = bg.add_belief(b)
                            new_beliefs_added += 1
                            contras = cd.check_new_belief(b, bg.query_all()[:30])
                            for contra in contras:
                                bg.add_contradiction(
                                    bid,
                                    contra.get("belief_a", ""),
                                    contra.get("explanation", ""),
                                )
                        bg.save()

                    md_parts = []
                    if analysis.get("decision_logic"):
                        md_parts.append(f"**决策逻辑**: {analysis['decision_logic']}")
                    if analysis.get("priorities"):
                        md_parts.append(f"**优先级**: {' > '.join(analysis['priorities'])}")
                    if analysis.get("thinking_style"):
                        md_parts.append(f"**思维特征**: {analysis['thinking_style']}")
                    if new_beliefs_added:
                        md_parts.append(f"*已提取 {new_beliefs_added} 条新信念写入图谱*")

                    done = tl.get_completed_count()

                    analysis_md = "\n\n".join(md_parts) if md_parts else "分析完成"

                    next_task = tl.get_next_task()
                    if next_task:
                        num = done + 1
                        dim_name = TASK_DIMENSIONS.get(next_task["dimension"], next_task["dimension"])
                        next_md = f"### 第 {num} 题 · {dim_name}\n\n{next_task['prompt']}"
                        return analysis_md, _task_progress_html(), next_md, next_task["id"], next_task["prompt"], gr.update(value="")
                    return analysis_md, _task_progress_html(), "**所有任务已完成！**", "", "", gr.update(value="")

                def _scan_contradictions():
                    if components is None:
                        return "系统未初始化"
                    cd = components["contradiction_detector"]
                    bg = components["belief_graph"]
                    tl = components["task_library"]
                    all_beliefs = bg.query_all()
                    if len(all_beliefs) < 2:
                        return "信念数量不足，请先完成更多任务或导入数据。"
                    contras = cd.full_scan(all_beliefs)
                    if not contras:
                        return "未发现信念矛盾。信念体系一致性良好。"
                    new_tasks = cd.generate_probe_tasks(contras, tl)
                    lines = [f"### 发现 {len(contras)} 组矛盾\n"]
                    for i, c in enumerate(contras, 1):
                        lines.append(f"**{i}. [{c.get('type', '')}]** {c.get('explanation', '')}")
                        if c.get("resolution_hint"):
                            lines.append(f"   可能解释: {c['resolution_hint']}")
                        if c.get("probe_question"):
                            lines.append(f"   验证问题: _{c['probe_question']}_")
                        lines.append("")
                    if new_tasks:
                        lines.append(f"*已自动生成 {len(new_tasks)} 个追问任务，点「开始校准」获取*")
                    return "\n".join(lines)

                from src.cognitive.task_library import TASK_DIMENSIONS

                next_task_btn.click(
                    fn=_next_task,
                    outputs=[task_display, task_current_id, task_current_prompt, task_progress_html],
                )
                submit_task_btn.click(
                    fn=_submit_task,
                    inputs=[task_current_id, task_current_prompt, task_response],
                    outputs=[task_analysis_output, task_progress_html, task_display, task_current_id, task_current_prompt, task_response],
                )
                scan_contradictions_btn.click(fn=_scan_contradictions, outputs=contradiction_output)

                demo.load(fn=_task_progress_html, outputs=task_progress_html)

            # ================================================================
            # Tab: Analytics Dashboard
            # ================================================================
            with gr.Tab("数据洞察", id="tab-analytics", visible=is_ready) as tab_analytics:
                refresh_analytics_btn = gr.Button("刷新分析", variant="secondary")

                overview_html = gr.HTML(label="数据概览")

                with gr.Row():
                    with gr.Column(scale=1):
                        contacts_html = gr.HTML()
                    with gr.Column(scale=1):
                        hourly_html = gr.HTML()

                monthly_html = gr.HTML()

                with gr.Row():
                    with gr.Column(scale=1):
                        relationship_html = gr.HTML()
                    with gr.Column(scale=1):
                        belief_summary_html = gr.HTML()

                persona_html = gr.HTML()

                analytics_outputs = [overview_html, contacts_html, hourly_html, monthly_html, relationship_html, belief_summary_html, persona_html]
                refresh_analytics_btn.click(fn=load_analytics, outputs=analytics_outputs)
                demo.load(fn=load_analytics, outputs=analytics_outputs)

            # ================================================================
            # Tab: Belief Graph
            # ================================================================
            with gr.Tab("内心地图", id="tab-beliefs", visible=is_ready) as tab_beliefs:
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
            with gr.Tab("记忆", id="tab-memories", visible=is_ready) as tab_memories:
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
            with gr.Tab("设置", id="tab-system"):
                info_output = gr.Textbox(label="系统状态", lines=12, interactive=False, show_copy_button=True)
                refresh_btn = gr.Button("刷新", variant="secondary")
                refresh_btn.click(fn=get_system_info, outputs=info_output)
                demo.load(fn=get_system_info, outputs=info_output)

                gr.Markdown("---\n### API 配置")
                gr.Markdown("修改后保存到 `config.yaml`，需重启生效。")
                with gr.Row():
                    sys_api_provider = gr.Dropdown(
                        label="Provider", choices=["openai", "anthropic", "gemini"],
                        value=_pv, scale=1,
                    )
                    sys_api_model = gr.Textbox(label="Model", value=_md, scale=2)
                with gr.Row():
                    sys_api_key = gr.Textbox(label="API Key", value=_ak, type="password", scale=3)
                with gr.Row():
                    sys_api_base = gr.Textbox(label="Base URL（留空用默认）", value=_bu, scale=3)
                sys_save_api_btn = gr.Button("保存 API 配置", variant="primary")
                sys_save_api_result = gr.HTML()
                sys_save_api_btn.click(
                    fn=_save_api,
                    inputs=[sys_api_provider, sys_api_model, sys_api_key, sys_api_base],
                    outputs=sys_save_api_result,
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
                        return '<span style="color:#a8969a">没有需要清除的数据。</span>'
                    return '<span style="color:#65a88a">✓ 已清除：{}</span>'.format(", ".join(removed))

                reset_all_btn.click(fn=_reset_all_training, outputs=reset_all_result)

        # Wire timer & page-load to update both training outputs and tab visibility
        _all_timer_outputs = [
            train_output, progress_timer,
            tab_chat, tab_cognitive, tab_analytics, tab_beliefs, tab_memories, tab_eval,
        ]
        progress_timer.tick(fn=_poll_tick, outputs=_all_timer_outputs)
        demo.load(fn=_on_page_load, outputs=_all_timer_outputs)

    return demo


if __name__ == "__main__":
    app = build_ui()
    app.queue()
    app.launch(show_api=False, server_port=7872)
