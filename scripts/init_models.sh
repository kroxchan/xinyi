#!/bin/bash
# ─────────────────────────────────────────────────────────────
# scripts/init_models.sh
# 预下载所有小模型（向量模型 + reranker + 情感分类器）
# 首次运行前执行，避免用户首次使用时卡顿
# ─────────────────────────────────────────────────────────────
set -e

echo "==> 预下载 xinyi 所需的小模型（约 1.1GB）..."

# 允许网络下载（临时解除 offline 限制）
export HF_HUB_OFFLINE=0
export TRANSFORMERS_OFFLINE=0

# 1. 向量嵌入模型（已有，触发表明已缓存则跳过）
python3 - <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.memory.embedder import TextEmbedder

emb = TextEmbedder(offline=False)
if emb.is_model_cached():
    print("  [跳过] 向量模型已缓存: shibing624/text2vec-base-chinese")
else:
    print("  [下载] 向量模型: shibing624/text2vec-base-chinese (~300MB)...")
    emb.download_model()
    print("  [完成] 向量模型下载完成")
PYEOF

# 2. Rerank 模型
python3 - <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.memory.reranker import BGEReranker

reranker = BGEReranker(offline=False)
if reranker.is_model_cached():
    print("  [跳过] Rerank 模型已缓存: BAAI/bge-reranker-base")
else:
    print("  [下载] Rerank 模型: BAAI/bge-reranker-base (~400MB)...")
    reranker.download_model()
    print("  [完成] Rerank 模型下载完成")
PYEOF

# 3. 情感分类模型（将在 P2-1 启用，提前下载）
python3 - <<'PYEOF'
import os, sys, torch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

model_name = "jefferyluo/bert-chinese-emotion"
safe_name = model_name.replace("/", "--")
hf_dir = os.path.expanduser(f"~/.cache/huggingface/hub/models--{safe_name}")
st_dir = os.path.expanduser(f"~/.cache/torch/sentence_transformers/{safe_name}")

cached = (os.path.exists(hf_dir) and any(os.listdir(hf_dir))) or \
          (os.path.exists(st_dir) and any(os.listdir(st_dir)))

if cached:
    print(f"  [跳过] 情感模型已缓存: {model_name}")
else:
    print(f"  [下载] 情感模型: {model_name} (~300MB)...")
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    AutoTokenizer.from_pretrained(model_name)
    AutoModelForSequenceClassification.from_pretrained(model_name)
    print(f"  [完成] 情感模型下载完成")
PYEOF

echo ""
echo "==> 所有模型下载完成！可以开始使用 xinyi 了。"
echo "    如需查看已缓存模型：ls ~/.cache/huggingface/hub/ | grep xinyi"
