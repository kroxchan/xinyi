# ============================================================
# PyInstaller spec for xinyi  |  macOS .app bundle
# Build:  pip install pyinstaller && pyinstaller xinyi.spec
#
# Usage:
#   开发/本地运行:  pyinstaller xinyi.spec
#   清理构建:       pyinstaller --clean xinyi.spec
# ============================================================
import os
import sys

from PyInstaller.building.build_main import (
    Analysis, PYZ, EXE, COLLECT, BUNDLE
)
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Resolve project root
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = sys._MEIPASS
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))

# ── Hidden imports ─────────────────────────────────────────
hiddenimports = [
    # Core
    "chromadb",
    "chromadb.api",
    "chromadb.api.rust",
    "chromadb.api.types",
    "chromadb.api.models",
    "gradio",
    "openai",
    "anthropic",
    "sentence_transformers",
    "sentence_transformers.CrossEncoder",
    # Data
    "pandas",
    "jieba",
    "jieba.posseg",
    "Crypto.Cipher",
    # Utils
    "yaml",
    "dotenv",
    "rich",
    "requests",
    "torch",
    "numpy",
    # Internal modules
    "src.config",
    "src.exceptions",
    "src.logging_config",
    "src.engine.chat",
    "src.engine.training",
    "src.utils.model_download",
    "src.memory.embedder",
    "src.memory.vector_store",
    "src.memory.retriever",
    "src.memory.memory_bank",
    "src.memory.reranker",
    "src.personality.prompt_builder",
    "src.personality.emotion_tracker",
    "src.personality.emotion_analyzer",
    "src.personality.analyzer",
    "src.belief.graph",
    "src.belief.extractor",
    "src.data.cleaner",
    "src.data.conversation_builder",
    "src.data.decrypt",
    "src.data.emotion_tagger",
    "src.data.privacy_redactor",
    "src.engine.learning",
    "src.engine.advisor_registry",
    "src.engine.partner_advisor",
    "src.engine.persona",
    "src.engine.session",
    "src.engine.advisor_registry",
    "src.mediation.mediator",
    # Personality
    "src.personality.prompt_builder",
    "src.personality.emotion_tracker",
    "src.personality.emotion_analyzer",
    "src.personality.analyzer",
    "src.personality.thinking_profiler",
    "src.personality.guidance",
    # Data
    "src.data.cleaner",
    "src.data.conversation_builder",
    "src.data.decrypt",
    "src.data.emotion_tagger",
    "src.data.privacy_redactor",
    "src.data.partner_config",
    "src.data.contact_registry",
    "src.data.parser",
    # Features
    "src.features.cooldown",
    "src.features.cooldown.cooldown_manager",
    "src.features.feedback",
    "src.features.feedback.authenticity_checker",
    "src.features.pre_send",
    "src.features.pre_send.pre_send_engine",
    "src.features.shareable_report",
    "src.features.shareable_report.single_perspective_report",
    "src.features.local_model",
    "src.features.local_model.presets",
    "src.features.ftue",
    "src.features.ftue.dual_mode_explainer",
    # Cognitive
    "src.cognitive.task_library",
    "src.cognitive.active_probe",
    "src.cognitive.contradiction_detector",
    "src.cognitive.inference_engine",
    # Belief
    "src.belief.contradiction",
    # Memory
    "src.memory.multi_md",
    "src.memory.multi_md.multi_md_manager",
    "src.memory.multi_md.distill",
    "src.memory.multi_md.bm25_search",
    "src.memory.multi_md.anchors",
    "src.memory.multi_md.topic_tracker",
    "src.memory.multi_md.curated_memory",
    "src.memory.multi_md.daily_log",
    # Eval
    "src.eval.evaluator",
    # UI (new)
    "src.ui.ux_helpers",
    "src.ui.styles",
    "src.ui.callbacks_api",
    "src.ui.app_state",
    "src.ui.shared",
    "src.ui.tabs",
    "src.ui.tabs.tab_setup",
    "src.ui.tabs.tab_system",
    "src.ui.tabs.tab_chat",
    "src.ui.tabs.tab_analytics",
    "src.ui.tabs.tab_beliefs",
    "src.ui.tabs.tab_cognitive",
    "src.ui.tabs.tab_eval",
    "src.ui.tabs.tab_memories",
    # Core
    "src.context",
]
hiddenimports += collect_submodules("chromadb.telemetry")
hiddenimports += collect_submodules("src.memory")
hiddenimports += collect_submodules("src.belief")
hiddenimports += collect_submodules("src.personality")
hiddenimports += collect_submodules("src.features")
hiddenimports += collect_submodules("src.engine")
hiddenimports += collect_submodules("src.ui")

# ── Assets to include ──────────────────────────────────────
datas = [
    (os.path.join(PROJECT_ROOT, ".env.example"), "."),
    (os.path.join(PROJECT_ROOT, "config.example.yaml"), "."),
]
datas += collect_data_files("gradio")
datas += collect_data_files("gradio_client")
datas += collect_data_files("chromadb")

module_collection_mode = {
    "gradio": "pyz+py",
    "gradio_client": "pyz+py",
}

a = Analysis(
    [os.path.join(PROJECT_ROOT, "src/__main__.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "pytest", "setuptools"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    module_collection_mode=module_collection_mode,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE (executable inside .app) ───────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xinyi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app — no terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── COLLECT (all files grouped together) ───────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="xinyi",
)

# ── BUNDLE (macOS .app) ────────────────────────────────────
app = BUNDLE(
    coll,
    name="xinyi.app",
    icon=None,
    bundle_identifier="com.xinyi.app",
    info_plist={
        "CFBundleName": "xinyi",
        "CFBundleDisplayName": "xinyi",
        "CFBundleIdentifier": "com.xinyi.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "xinyi",
        "LSMinimumSystemVersion": "10.15",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        # Not a menu-bar-only app — show in Dock so macOS doesn't kill it
        "LSUIElement": False,
    },
    pyz=None,
)
