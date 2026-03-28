# ============================================================
# PyInstaller spec for xinyi  |  Windows .exe
# Build (Windows):  pyinstaller xinyi-windows.spec
# ============================================================
import os
import sys

from PyInstaller.building.build_main import (
    Analysis, PYZ, EXE, COLLECT
)

block_cipher = None

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = sys._MEIPASS
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))

hiddenimports = [
    # Core
    "chromadb",
    "gradio",
    "gradio.blocks",
    "gradio.routes",
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
    # Internal
    "src.config",
    "src.exceptions",
    "src.logging_config",
    "src.engine.chat",
    "src.engine.training",
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
    # Windows-specific
    "win32api",
    "win32con",
]

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

# ── Windows console exe ────────────────────────────────────
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
    console=True,          # Windows: show console so users see logs/errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    manifest=None,
    version=None,
    resources=[],
)

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
