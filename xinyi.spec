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
]

# ── Assets to include ──────────────────────────────────────
datas = [
    (os.path.join(PROJECT_ROOT, ".env.example"), "."),
    (os.path.join(PROJECT_ROOT, "config.example.yaml"), "."),
]

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
    },
    pyz=None,
)
