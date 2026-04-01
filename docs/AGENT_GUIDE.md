# 心译（xinyi）Agent 开发指南

> 本文档为 AI 助手编写，面向长期上下文不丢、项目结构清晰、模块职责明确而写。
> 目标：任何 Agent 接手心译开发时，能直接开始干活，不需要额外探索。

---

## 项目概述

**心译**是一个从微信聊天记录构建「数字分身」的 AI 工具，让用户通过分析自己的聊天数据，理解自己的表达模式与关系模式。

- **Slogan**: 发出去之前，先译一下。
- **GitHub**: https://github.com/kroxchan/xinyi
- **核心问题**: 恋爱/关系中 80% 的争吵不是因为观点不同，而是因为表达方式不对。心译翻译的是「没说出来的意思」。

### 两种训练模式

| 模式 | 学谁的消息 | 谁来对话 | 典型用法 |
|------|-----------|---------|---------|
| 训练自己 | 你发出的消息 | 对象和分身聊 | 练习表达、看清自己的沟通模式 |
| 训练对象 | TA 发出的消息 | 你和分身聊 | 理解 TA 为什么那样说 |

---

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **前端 UI** | Gradio |
| **对话引擎** | OpenAI / Anthropic / Gemini（OpenAI 兼容接口）|
| **向量检索** | ChromaDB |
| **嵌入模型** | `shibing624/text2vec-base-chinese`（本地，~400MB）|
| **重排模型** | `BAAI/bge-reranker-base`（可选，本地，~400MB）|
| **情感分类** | `Johnson8187/Chinese-Emotion-Small`（可选，本地，~1.1GB）|
| **微信解密** | `ylytdeng/wechat-decrypt`（内存解密，支持 macOS/Windows 4.x）|
| **配置管理** | Pydantic + YAML + python-dotenv |
| **打包** | PyInstaller + briefcase |

> 所有本地模型 **CPU 可跑**，无需显卡。国内用户可通过 `HF_ENDPOINT=https://hf-mirror.com` 加速下载。

---

## 目录结构

```
xinyi/
├── src/                        # 所有业务代码
│   ├── __main__.py            # 入口：load_config → build_ui → launch
│   ├── app.py                 # Gradio 总装，全局状态、UI 回调
│   ├── config.py              # Pydantic 配置层（load_config / get_config）
│   ├── context.py             # 全局状态上下文（共享 gr.State）
│   ├── exceptions.py           # 业务异常 + exc_to_user_msg
│   ├── logging_config.py       # 日志初始化
│   │
│   ├── engine/                 # 对话与训练核心
│   │   ├── chat.py            # ChatEngine：主对话引擎，编排检索→内心独白→LLM→流式输出
│   │   ├── training.py        # 训练流水线入口
│   │   ├── learning.py         # 学习循环
│   │   ├── session.py          # 会话管理
│   │   ├── persona.py          # 人格数据加载
│   │   ├── partner_advisor.py  # @KK 关系顾问
│   │   └── advisor_registry.py # 顾问引擎注册与热重载
│   │
│   ├── memory/                 # 多路记忆
│   │   ├── vector_store.py     # ChromaDB 操作（持久化向量检索）
│   │   ├── embedder.py         # 嵌入模型封装
│   │   ├── retriever.py        # MemoryRetriever：多路召回编排
│   │   ├── reranker.py         # BGE 重排
│   │   ├── memory_bank.py      # 结构化事实（类型/置信度/来源）
│   │   └── multi_md/           # 多维记忆（BM25 / daily_log / topic_tracker / curated_memory 等）
│   │
│   ├── belief/                 # 信念图谱
│   │   ├── extractor.py        # 从对话片段提取信念（topic/stance/condition/confidence）
│   │   ├── graph.py            # BeliefGraph：信念存储与检索
│   │   ├── contradiction.py   # 矛盾检测
│   │   └── extractor.py        # 信念抽取逻辑
│   │
│   ├── personality/            # 人格引擎
│   │   ├── prompt_builder.py   # PromptBuilder：多层 Prompt 组装（Tier 0-3）
│   │   ├── emotion_tracker.py  # 情绪状态机（惯性/传染/阈值）
│   │   ├── emotion_analyzer.py # 情绪分析
│   │   ├── analyzer.py         # 人格画像分析
│   │   ├── thinking_profiler.py# 思维画像（IF-THEN 指令集）
│   │   ├── guidance.py         # GuidanceManager：从 data/guidance/*.md 加载人格指导文件
│   │   └── guidance_manager.py # 同上（旧名）
│   │
│   ├── cognitive/              # 认知校准
│   │   ├── task_library.py     # 8 类情境题库（价值权衡/冲突处理/信任校准等）
│   │   ├── active_probe.py     # 主动探测任务
│   │   ├── inference_engine.py # 从选择反推决策逻辑
│   │   └── contradiction_detector.py # 认知矛盾检测
│   │
│   ├── data/                   # 数据处理
│   │   ├── parser.py           # 微信消息解析
│   │   ├── cleaner.py          # 清洗（去系统消息/群聊/脱敏）
│   │   ├── decrypt.py          # 微信解密接口封装
│   │   ├── conversation_builder.py # 对话片段构建（按情境分桶）
│   │   ├── emotion_tagger.py   # 情感标签标注
│   │   ├── privacy_redactor.py # PII 自动脱敏（手机号/身份证/邮箱）
│   │   ├── contact_registry.py # 联系人注册表
│   │   └── partner_config.py   # 训练对象配置
│   │
│   ├── eval/                   # 分身诊断
│   │   └── evaluator.py        # 分身评分评估
│   │
│   ├── features/               # 功能模块
│   │   ├── cooldown/           # 冷却期管理
│   │   ├── pre_send/           # 预发送分析（"你这句话会被怎么理解"）
│   │   ├── feedback/           # 真实性反馈
│   │   ├── ftue/               # 首次引导（DualModeExplainer 等）
│   │   ├── local_model/        # 本地模型预设
│   │   └── shareable_report/   # 可分享报告
│   │
│   ├── mediation/              # 调解引擎
│   │   └── mediator.py         # 调解逻辑
│   │
│   └── ui/                     # UI 层
│       ├── tabs/               # 8 个功能 Tab 组件
│       │   ├── tab_setup.py    # 连接：API 配置/微信解密/训练
│       │   ├── tab_chat.py    # 心译对话
│       │   ├── tab_analytics.py# 关系报告
│       │   ├── tab_cognitive.py# 校准
│       │   ├── tab_beliefs.py # 内心地图
│       │   ├── tab_memories.py# 记忆
│       │   ├── tab_eval.py    # 评估
│       │   └── tab_system.py  # 设置
│       ├── app_state.py       # Gradio State 封装
│       ├── callbacks_api.py   # 设置页读写 config.yaml + 触发重载
│       ├── shared.py          # UI 共享组件
│       ├── styles.py          # 样式常量
│       └── ux_helpers.py      # UX 辅助函数
│
├── tests/                      # pytest 单元测试
├── docs/                       # 文档
│   ├── 使用说明.md             # 用户使用手册（面向用户）
│   ├── installation.md        # 详细安装指南
│   ├── architecture.md         # 技术架构文档
│   ├── privacy.md             # 隐私与数据安全
│   └── ...
├── vendor/wechat-decrypt/     # 微信解密子模块（独立仓库）
├── config.default.yaml         # 配置文件模板
├── .env.example                # 环境变量模板
├── requirements.txt            # Python 依赖
└── README.md                   # 项目总览
```

---

## 核心模块详解

### 1. 配置系统（`src/config.py`）

**单例模式**，全项目唯一入口。所有配置读取统一走这里。

```python
from src.config import load_config, get_config, AppConfig

load_config()          # 加载 .env → 解析 config.yaml → 解析环境变量
config = get_config() # 返回 AppConfig 单例
```

**环境变量语法**：`${VAR_NAME:default}`，在 `.env` 或 `config.yaml` 中均可使用。

**配置结构**（Pydantic 模型）：

| 模型 | 主要字段 |
|------|---------|
| `APIConfig` | provider, api_key, model, extraction_model, base_url, headers |
| `EmbeddingConfig` | model, device |
| `PathsConfig` | raw_db_dir, processed_dir, chroma_dir, beliefs_file, persona_file 等 |
| `ChunkingConfig` | max_turns, min_turns, time_gap_minutes |
| `RetrievalConfig` | top_k_vectors, top_k_beliefs |
| `RerankConfig` | enabled, provider, model, device, top_k_raw, top_k_reranked |
| `EmotionConfig` | enabled, provider, model, emotion_boost_weight |
| `LoggingConfig` | level, dir, rotation, retention |

**向后兼容**：同时支持 `config["key"]` 字典接口，详见 `src/config.py` 的 `ConfigDictProxy`。

---

### 2. 对话引擎（`src/engine/chat.py`）

**ChatEngine** 是整个应用的核心，每次对话经历以下流程：

```
用户消息
  ↓
多路召回（向量检索 + BM25 + MemoryBank + BeliefGraph）
  ↓
BGE 重排（top 20 → top 5）
  ↓
@KK 检测 → 切换到 PartnerAdvisor
  ↓
内心独白（Inner Thought）：LLM 评估对方情绪、分身第一反应、心理背景
  ↓
Prompt 组装（Tier 0-3，详见 PromptBuilder）
  ↓
LLM 流式生成回复
  ↓
返回给前端（WebSocket 流式输出）
```

**初始化**：

```python
chat_engine = ChatEngine(config["api"])
chat_engine.set_components(
    memory_retriever=...,
    belief_graph=...,
    prompt_builder=...,
    vector_store=...,
    emotion_tracker=...,
    memory_bank=...,
)
```

**对话调用**：

```python
result = chat_engine.chat(
    user_message="我想和你谈谈",
    chat_history=[{"role": "user", "content": "..."}, ...],
    contact_wxid="wxid_xxx",
    contact_context={"name": "女友", "rel_type": "partner"},
)
```

**情绪类型常量**（`VALID_EMOTIONS`）：

```
joy, excitement, touched, gratitude, pride,
sadness, anger, anxiety, disappointment, wronged,
coquettish, jealousy, heartache, longing,
curiosity, neutral
```

**关系类型标签**（`_REL_TYPE_LABELS`）：partner / family / friend / colleague / stranger / self / default

---

### 3. 记忆系统

心译采用**多路召回**架构，每路互补：

| 记忆类型 | 存储方式 | 召回方式 | 特点 |
|---------|---------|---------|------|
| **向量记忆** | ChromaDB | 语义相似度 | 语义相近的对话片段 |
| **BM25** | 内存 | 关键词匹配 | 精确话题召回 |
| **MemoryBank** | JSON/YAML | 类型+关键词 | 高精度结构化事实 |
| **信念图谱** | JSON | 话题+立场 | 立场类知识，置信度高 |

**检索流程**（`src/memory/retriever.py`）：

```python
results = retriever.retrieve(
    query="你最近怎么总是不回我消息",
    contact_filter="wxid_xxx",
    top_k_vectors=5,
    top_k_beliefs=3,
    emotion_filter="sadness",      # 可选，情绪匹配加权
)
# 返回: {"memories": [...], "beliefs": [...], "bm25_hits": [...]}
```

---

### 4. 信念图谱（`src/belief/`）

信念 = **立场 + 前提条件 + 来源**。与关键词不同，信念表达的是「你怎么看这件事」。

**信念提取 Prompt**（`src/belief/extractor.py`）：

```python
# 关键规则：
# 1. 只提取「我」说的内容中表达的观点，对方消息仅作上下文
# 2. 每条信念: topic / stance / condition / confidence(0-1)
# 3. 返回严格 JSON 数组
```

**信念结构**：

```json
{
  "topic": "关于道歉",
  "stance": "倾向于先冷静再处理，而不是当场解决",
  "condition": "当对方也在情绪中时",
  "confidence": 0.85,
  "source_chunks": ["chunk_id_1", "chunk_id_2"]
}
```

---

### 5. Prompt 组装（`src/personality/prompt_builder.py`）

**分层架构**，静动分离：

| Tier | 层级 | 来源 | 说明 |
|------|------|------|------|
| **Tier 0** | CRITICAL | rules.md, identity.md | 永远全量加载 |
| **Tier 1** | HIGH | style.md, thinking.md | 全量，超长时截断 |
| **Tier 2** | MEDIUM | emotion.md | 按 budget 截断 |
| **Tier 3** | DYNAMIC | memories/beliefs/few-shot/emotion/inner_thought | 每轮动态注入 |

**人格指导文件**（`data/guidance/`）由 `GuidanceManager` 在首次启动时自动生成：

- `identity.md` — 分身是谁，在和谁说话
- `rules.md` — 核心行为规则
- `style.md` — 说话风格（语气/词汇/习惯）
- `thinking.md` — 思维方式（决策逻辑/优先级）
- `emotion.md` — 情绪模式（阈值/惯性/触发器）

---

### 6. 训练流水线（`src/engine/training.py`）

```
扫描消息 → 去重/清洗/脱敏
  → 按情境分桶（甜蜜/冲突/日常/脆弱…）
  → 向量化 + ChromaDB 建库
  → LLM 提取信念（BeliefGraph）
  → LLM 提取结构化事实（MemoryBank）
  → 生成思维画像（IF-THEN 指令集）
  → 生成情绪档案（阈值/触发器/表达习惯）
  → 生成人格指导文件（data/guidance/*.md）
```

**数据路径**：

| 路径 | 内容 |
|------|------|
| `data/raw/` | 原始微信数据库副本（解密后） |
| `data/processed/` | 清洗后的消息 JSON |
| `data/chroma_db/` | ChromaDB 向量库 |
| `data/beliefs.json` | 信念图谱 |
| `data/persona_profile.yaml` | 人格画像 |
| `data/emotion_profile.yaml` | 情绪档案 |
| `data/thinking_model.txt` | 思维画像 |
| `data/guidance/*.md` | 人格指导文件（自动生成） |

---

### 7. 情绪状态机（`src/personality/emotion_tracker.py`）

情绪不是即时切换，而是有**惯性**、**传染**、**阈值**：

- **惯性**：负面情绪衰减比正面慢
- **传染**：对方情绪会影响分身
- **阈值**：每个人有不同的炸点

情感分类可选开启（`config.yaml` → `emotion.enabled: true`），每个 chunk 打上情绪标签后，检索时优先召回情绪相近的片段。

---

## UI 系统（Gradio）

### 全局状态（`src/context.py` / `src/ui/app_state.py`）

Gradio 的 `gr.State` 无法跨 Tab 共享，心译通过**单例 Context** 管理：

```python
from src.context import AppContext

ctx = AppContext.get()
ctx.chat_engine       # 对话引擎
ctx.memory_retriever  # 检索器
ctx.belief_graph      # 信念图谱
# ...所有核心组件
```

### Tab 模块

每个 Tab 是独立文件，入口统一通过 `src/ui/tabs/__init__.py` 导出：

| Tab | 文件 | 功能 |
|-----|------|------|
| 连接 | `tab_setup.py` | API 配置/微信解密/训练 |
| 心译对话 | `tab_chat.py` | 与分身聊天，@KK 顾问 |
| 关系报告 | `tab_analytics.py` | 全景关系分析 |
| 校准 | `tab_cognitive.py` | 情境题校准 |
| 数据洞察 | Tab（集成在 analytics）| 消息统计 |
| 内心地图 | `tab_beliefs.py` | 信念图谱查看/搜索 |
| 记忆 | `tab_memories.py` | MemoryBank 管理 |
| 设置 | `tab_system.py` | API 配置/模型状态 |

---

## 隐私与脱敏

**数据流向**：

- `data/` 目录：所有本地存储，不上传
- API 请求：对话上下文 + 检索片段 + few-shot 示例，**分批发送**，**不发送原始数据库**
- 脱敏（`src/data/privacy_redactor.py`）：手机号/身份证/邮箱自动脱敏

**完全离线**：配置 Ollama 或 vLLM 即可，所有 LLM 推理在本地完成。

---

## 常见开发任务模板

### 添加新的对话前处理器

在 `ChatEngine.chat()` 流程中，找到 `user_message` 处理位置：

```python
# src/engine/chat.py → chat() 方法
# 在多路召回之前插入预处理器
processed_message = self._preprocess_message(user_message)
```

### 新增一个 UI Tab

1. 在 `src/ui/tabs/` 创建 `tab_new_feature.py`
2. 在 `src/ui/tabs/__init__.py` 导出
3. 在 `src/app.py` 的 `build_ui()` 中注册路由
4. 在 `src/ui/callbacks_api.py` 中注册后端回调（如需要）

### 修改配置字段

1. 在 `src/config.py` 的对应 Pydantic 模型中添加字段
2. 在 `config.default.yaml` 中添加默认值
3. 在 `docs/architecture.md` 的配置表中更新说明

### 添加新的记忆类型

1. 在 `src/memory/multi_md/` 下创建新模块
2. 在 `src/memory/retriever.py` 的 `retrieve()` 中集成召回逻辑
3. 在 `src/engine/training.py` 的流水线中添加提取步骤

---

## 开发规范

- **代码格式**: `black . && isort .`
- **Commit message**: 中文，格式 `[模块] 简短描述`
- **文档同步**: 新增用户可见功能 → 同步更新 `docs/` 和 `README.md`
- **测试**: `pytest tests/ -v`，新增功能请同步写测试
- **环境变量语法**: `${VAR:default}`，详见 `src/config.py`

---

## 快速启动

```bash
git clone https://github.com/kroxchan/xinyi.git
cd xinyi
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填入 API Key
python -m src         # 启动开发版
# 浏览器访问 http://localhost:7872
```

---

## 相关文档

| 文档 | 受众 | 内容 |
|------|------|------|
| `README.md` | 用户/贡献者 | 项目总览、快速上手 |
| `docs/使用说明.md` | 用户 | 完整功能说明、图文教程 |
| `docs/installation.md` | 用户/开发者 | 三种安装方式、故障排除 |
| `docs/architecture.md` | 开发者 | 核心架构、数据流、配置表 |
| `docs/privacy.md` | 用户 | 隐私与数据安全 |
| `CONTRIBUTING.md` | 贡献者 | 开发规范、PR 检查清单 |
| 本文档 | AI Agent | 项目全局上下文、模块关系、任务模板 |
