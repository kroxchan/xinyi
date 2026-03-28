"""Standalone import check for CI diagnostics."""
import sys
import traceback

sys.path.insert(0, ".")

modules = [
    ("src.config", "AppConfig"),
    ("src.exceptions", "XinyiBaseError"),
    ("src.logging_config", "setup_logging"),
    ("src.memory.reranker", "build_reranker"),
    ("src.memory.embedder", "TextEmbedder"),
    ("src.memory.vector_store", "VectorStore"),
    ("src.memory.retriever", "MemoryRetriever"),
    ("src.data.emotion_tagger", "build_tagger"),
    ("src.data.privacy_redactor", "PrivacyRedactor"),
    ("src.engine.advisor_registry", "get_registry"),
    ("src.personality.emotion_analyzer", "EmotionAnalyzer"),
    ("src.personality.emotion_tracker", "EmotionTracker"),
    ("src.personality.prompt_builder", "PromptBuilder"),
    ("src.belief.graph", "BeliefGraph"),
    ("src.data.cleaner", "MessageCleaner"),
    ("src.data.conversation_builder", "ConversationBuilder"),
    ("src.engine.chat", "ChatEngine"),
]

failed = []
for module, name in modules:
    try:
        mod = __import__(module, fromlist=[name])
        getattr(mod, name)
        print(f"  OK  {module}.{name}")
    except Exception as e:
        print(f"  FAIL  {module}.{name}: {e}")
        failed.append((module, name, e))
        traceback.print_exc()

if failed:
    print(f"\n{len(failed)} import(s) failed!")
    sys.exit(1)
else:
    print("\nAll imports OK!")
