# 技术架构

本文档详细介绍心译的核心模块、技术选型与数据流。适合想深入理解原理或参与开发的朋友。

> [README 快速导航](../README.md) | [使用说明](../使用说明.md) | [隐私说明](privacy.md)

---

## 整体数据流

```
微信加密数据库（SQLCipher 4）
    ↓ 内存密钥提取（macOS: find_all_keys_macos / Windows: find_all_keys_windows）
原始消息
    ↓ 清洗（去系统消息、PII 脱敏、群聊过滤）
    ↓ 按训练模式筛选（你的消息 or TA 的消息）
对话片段（Chunk）
    ↓ 情感感知分块（可选，给 chunk 打上情绪标签 → 写入向量库 metadata）
    ↓ 按情境分桶 + 向量化
    ├── ChromaDB 向量记忆（对话检索 + BGE 重排 + few-shot 采样）
    ├── BM25 关键词记忆（多路召回互补）
    ├── MemoryBank 结构化事实（置信度加权）
    ├── BeliefGraph 信念图谱（立场 + 条件 + 来源）
    ├── 思维画像（IF-THEN 指令集）
    └── 情绪档案（表达习惯 + 阈值 + 触发器）
         ↓
    多层 Prompt 组装
    ├── Tier 0: 身份锚定（分身是谁，在和谁说话）
    ├── Tier 1: 思维模型 + 说话风格
    ├── Tier 2: 情绪状态 + 过渡逻辑
    └── Tier 3: 实时注入（内心独白 + 记忆 + 信念 + few-shot）
         ↓
    对话输出（微信短句风格）
```

---

## 核心模块

### `src/engine/chat.py` — 对话引擎

- **检索阶段**：向量检索（ChromaDB） + BM25 多路召回 → BGE/bge-reranker-base 重排 → 取 Top 5
- **内心独白**：每次回复前 LLM 做认知评估——对方情绪、分身第一反应、心理状态
- **流式输出**：WebSocket 流式，逐 token 输出，带失败重试逻辑
- **@KK 顾问**：当用户消息含 `@KK` 时，切换到 `partner_advisor.py`，基于双方聊天摘要生成建议

### `src/engine/training.py` / `learning.py` — 训练流水线

```
扫描消息 → 去重/清洗/脱敏
  → 按情境分桶（甜蜜/冲突/日常/脆弱 …）
  → 向量化 + ChromaDB 建库
  → LLM 提取信念（BeliefGraph）
  → LLM 提取结构化事实（MemoryBank）
  → 生成思维画像（IF-THEN 指令集）
  → 生成情绪档案（阈值/触发器/表达习惯）
```

### `src/belief/` — 信念图谱

- 从对话片段中提取「立场 + 前提条件 + 结论」
- 支持矛盾检测（当两个信念在同场景下互斥时，生成验证任务）
- 信念参与每次对话检索，话题涉及 TA 在意的事时优先召回

### `src/personality/` — 思维画像与情绪

- **思维画像**：IF-THEN 指令集，如「当对方超过 3 小时未回复时，倾向于主动发消息确认关系安全感」
- **情绪状态机**：惯性（负面情绪衰减慢）、传染（对方情绪影响分身）、阈值（每个人的炸点）
- **情感感知分块**（可选）：每个 chunk 打上情绪标签（开心/生气/委屈/撒娇等），检索时优先召回与当前情绪一致的片段

### `src/memory/` — 多路记忆

| 类型 | 说明 |
|------|------|
| ChromaDB | 向量检索，语义相似度匹配 |
| BM25 | 关键词召回，与向量检索互补 |
| MemoryBank | 结构化事实（类型/内容/置信度/来源），高精度低召回 |
| 信念图谱 | 立场类知识，优先参与相关话题对话 |

### `src/cognitive/` — 认知校准

- 8 类情境题库（价值权衡、冲突处理、信任校准、情绪回应、身份边界等）
- 从选择中反推决策逻辑，而非相信自我描述
- 推断结果反馈进信念图谱，形成闭环

---

## 关键模型（全部 CPU 可跑，无需显卡）

| 用途 | 模型 | 大小 | 推理耗时 |
|------|------|------|---------|
| 向量化 | `shibing624/text2vec-base-chinese` | ~400MB | ~50ms/次 |
| 重排（可选） | `BAAI/bge-reranker-base` | ~400MB | ~100ms/次 |
| 情感分类（可选） | `Johnson8187/Chinese-Emotion-Small` | ~1.1GB | <100ms/chunk |

---

## 配置文件速查

`config.yaml` 中关键字段说明：

| 字段 | 说明 |
|------|------|
| `api.provider` | `openai` / `anthropic` / `gemini` |
| `api.api_key` | 从 `.env` 读取，支持 `${VAR}` 语法 |
| `api.model` | 对话主模型，默认 `gpt-4o` |
| `embedding.model` | 向量化模型名 |
| `rerank.enabled` | 是否启用重排，默认 `true` |
| `emotion.enabled` | 是否启用情感分块，默认 `false` |
| `paths.chroma_dir` | 向量库存储路径，默认 `data/chroma_db` |
| `logging.level` | 日志级别，默认 `INFO` |

环境变量支持 `${VAR:默认值}` 语法，`.env` 由 `python-dotenv` 加载（见 `src/config.py`）。

---

## `src/` 目录职责速查

| 路径 | 职责 |
|------|------|
| `src/__main__.py` | 入口：`load_config` → `build_ui` → `launch(inbrowser=True)` |
| `src/app.py` | Gradio 总装：全局状态、`build_ui`、业务回调 |
| `src/config.py` | Pydantic 配置模型与 `load_config` / `get_config` |
| `src/exceptions.py` | 业务异常类型与 `exc_to_user_msg` |
| `src/logging_config.py` | 日志初始化 |
| `src/engine/chat.py` | 主对话引擎：检索、内心独白、流式回复与重试 |
| `src/engine/training.py` / `learning.py` | 训练流水线与学习循环 |
| `src/engine/partner_advisor.py` | 关系顾问 @KK |
| `src/engine/advisor_registry.py` | 顾问/调解器实例注册与热重载 |
| `src/engine/session.py` | 会话管理 |
| `src/memory/*` | 嵌入、Chroma 向量库、检索、重排、MemoryBank、BM25 |
| `src/belief/*` | 信念抽取、图谱、矛盾检测 |
| `src/personality/*` | 提示词组装、情绪跟踪、思维画像 |
| `src/data/*` | 微信解析、清洗、解密、分块、脱敏 |
| `src/cognitive/*` | 校准任务库、主动探测、推理 |
| `src/eval/evaluator.py` | 分身诊断评分 |
| `src/features/*` | 冷却期、预发送、报告、FTUE 等 |
| `src/ui/tabs/*` | 各功能 Tab 组件 |
| `src/ui/callbacks_api.py` | 设置页读写 `config.yaml`、触发客户端重载 |

更细的接口以代码 docstring 为准。欢迎通过 PR 补充文档。

---

## 工程化特性

| 模块 | 说明 |
|------|------|
| Tab 模块化 | UI 按功能页拆分到 `src/ui/tabs/` |
| 日志体系 | `src/logging_config.py`，支持落盘 |
| 异常处理 | `src/exceptions.py` 语义化异常 + 统一错误卡片 |
| 测试 | `tests/` pytest，覆盖清洗/检索/嵌入/信念图/异常等 |
| 隐私脱敏 | `src/data/privacy_redactor.py`，可配置脱敏规则 |
| API 热重载 | 设置页保存后自动重建客户端与顾问引擎 |
| 打包 | PyInstaller + briefcase，安装包可写目录生成配置 |
| CI | GitHub Actions push main 构建 macOS/Windows zip 并更新 Release |
