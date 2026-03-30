# 心译

> 发出去之前，先译一下。
> 用你们真实的聊天记录，AI 帮你理解伴侣/亲人——或被理解。

心译读你们的真实微信聊天记录，构建一个说话方式和思维模式都接近真人的「数字分身」，帮助你更了解自己/对方。你可以选择训练谁的分身——

- **训练自己**：学你的说话风格。对象可以和「你的分身」聊，看你平时是怎么表达的
- **训练对象**：学 TA 的说话风格。你可以和「TA 的分身」对话，理解 TA 为什么那样说

两种模式用的是同一套引擎，差别只在于从谁的消息里学习。

---

## 为什么做这个

恋爱中大多数争吵不是因为观点不同，而是因为表达方式不对。

你明明想说「我需要你」，出口变成「你从来不在意我」。TA 想说「我也很累」，你听到的是「你的感受不重要」。

心译不教话术，也不替你做决定。它做的事很简单：**用真实聊天数据，帮你看清说话的人到底在想什么。**

---

## 安装与运行

**怎么选？** 不想装 Python → 用 **安装包**；要解密本机微信 → 用 **源码环境**（Windows 需管理员）；已有解密好的 `data/` → 可用 **Docker**。

### 方式一：安装包（macOS / Windows）

适合绝大多数用户：无需 Python，双击运行，启动后会**尝试自动打开浏览器**访问控制台（默认 `http://127.0.0.1:7872`；若未弹出请手动打开）。

👉 [Releases 下载最新版](https://github.com/kroxchan/xinyi/releases/latest)

| 系统 | 文件 | 说明 |
|------|------|------|
| macOS | `xinyi-macos.zip` | 解压后双击 `xinyi.app`；若提示未识别开发者：系统设置 → 隐私与安全性 → **仍要打开** |
| Windows | `xinyi-windows.zip` | 解压后双击 `xinyi.exe`；会显示**黑色控制台窗口**（日志输出），请勿关闭 |

**配置文件与数据放哪？**

- 安装包会在 **可写目录** 下自动生成 `config.yaml` 和 `data/`（与 macOS 上 `.app` 同级的文件夹；若该目录无写权限，macOS 会退回到 `~/Library/Application Support/xinyi`）。
- 首次运行若没有配置，会从内置模板复制 `config.example.yaml`。在界面 **设置 / 系统** 中填写 API Key 并保存即可。

更细的图文步骤见 [INSTALL.md](INSTALL.md)。

---

### 方式二：源码安装（最稳，支持微信解密）

#### 环境要求

- Python **3.9+**（CI 使用 3.11；`pyproject.toml` 中 briefcase 声明为 ≥3.10，建议 3.10+）
- macOS / Windows / Linux
- 任意 **OpenAI 兼容** API（OpenAI、Anthropic、DeepSeek、硅基流动等）

#### 安装依赖

```bash
git clone https://github.com/kroxchan/xinyi.git
cd xinyi
pip install -r requirements.txt
```

#### 配置

```bash
cp .env.example .env
# 编辑 .env，填入 API Key
```

或：

```bash
cp config.default.yaml config.yaml
# 编辑 config.yaml：api_key、base_url、model 等
```

> `.env` 与 `config.yaml` 已在 `.gitignore` 中，不会被提交。

#### 启动

```bash
# 推荐（与 run.sh 一致）
python -m src

# 亦可
python src/app.py
```

浏览器访问 **http://localhost:7872**
（或日志里打印的地址），按向导：**连接 → 选 TA → 训练模式 → 学习**。

> 首次训练会自动下载嵌入 / 重排 / 情感等模型；国内可设 `HF_ENDPOINT=https://hf-mirror.com` 再启动以加速 Hugging Face 下载。

**Windows 解密微信数据**：需 **管理员** 终端（Win+X → PowerShell 管理员）再运行上述命令。

---

### 方式三：Docker（不解密微信）

容器内**无法**完成微信内存解密。仅适合已有处理好的 `data/` 或使用外部解密流程的用户。

```bash
docker build -t xinyi .
docker run -it -p 7872:7872 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/data:/app/data \
  xinyi
```

或使用 `docker-compose`（先准备 `config.yaml`）：

```bash
cp config.default.yaml config.yaml
# 编辑 config.yaml 填入 API Key
docker-compose up
```

---

## 两种训练模式

启动后在「选择 TA」页面选定聊天对象，然后选择训练模式：

| 模式 | 分身是谁 | 学的是谁的消息 | 典型用法 |
|------|---------|-------------|---------|
| 训练自己 | 你 | 你发出的消息 | 练习表达、回顾自己的沟通模式 |
| 训练对象 | TA | TA 发出的消息 | 理解 TA 的想法、模拟 TA 会怎么回 |

选好后一键学习，后续所有功能（对话、报告、校准）都基于这个选择。想换？重新选模式再训练一次就行。

---

## 核心能力

### 1. 对话引擎：先想，再说

```
普通 AI：给它一段人设 → 开始表演
心译：读几千条真实聊天 → 学会一个人的思维和表达
```

- **内心独白**：每次回复前，引擎先做一轮认知评估——对方什么情绪、分身的第一反应是什么、当前心理状态——然后才生成回复
- **真实风格采样**：从向量库中实时抽取和当前话题最相似的几段真实对话作为语气参照，不是手写示例，是那个人真正说过的话
- **关系顾问 @KK**：对话中输入 `@KK`，顾问介入。KK 读过你们的聊天摘要，了解双方的沟通模式，用微信短句说话而不是咨询师腔调
- **RAG 重排**：向量检索后经 BAAI/bge-reranker-base 重排，优先召回与当前语境最匹配的对话片段（先召回 20 条，重排后取前 5 条）

### 2. 思维画像：从聊天记录里提取一个人的「操作系统」

不是做性格测试，也不是让 AI 写一段人设。心译的做法是：

1. 按情境分桶——甜蜜时怎么说、吵架时怎么说、脆弱时怎么说、日常闲聊怎么说
2. 每个情境下提取认知模式——决策逻辑、情绪触发点、回避模式
3. 跨情境交叉验证——只保留在多种场景下都一致的模式
4. 压缩成可执行指令——不是「这个人比较敏感」，而是「当对方超过 3 小时未回复时，倾向于主动发消息确认关系安全感」

这就是为什么分身的回复不像 AI，像那个人。

### 3. 信念图谱

从聊天记录中提取的不是关键词，是**立场**：

- 「关于加班：认为偶尔可以接受，但不应该常态化（前提：有对等回报）」
- 「关于道歉：倾向于先冷静再处理，而不是当场解决」
- 「关于金钱：回避直接讨论，但会通过行为暗示底线」

信念自动参与每次对话——当话题涉及在意的事时，分身不会敷衍，会用那个人真正的态度回应。系统还会自动检测信念之间的矛盾，生成验证任务。

### 4. 情绪状态机

不是给一个标签（正面/负面/中性），是模拟情绪的物理规律：

- **惯性**：刚吵完架不可能一秒变开心，负面情绪衰减比正面慢
- **传染**：对方的情绪影响分身的状态，但影响权重因人而异
- **阈值**：每个人的「炸点」不同，心译从真实记录中学到阈值在哪里

连续对话中情绪变化是连贯的，不会上一句还在生气，下一句突然温柔。

**情感感知分块**（可选）：训练阶段给每个对话片段打上情感标签（开心/生气/委屈等），写入向量库 metadata；检索时优先召回与当前情绪一致的聊天片段，适配不同情绪语境。

### 5. 认知校准

8 类情境任务（不是问卷），例如：

| 维度 | 例子 |
|------|-----|
| 价值权衡 | 朋友找你借一大笔钱 |
| 冲突处理 | 和父母在重大决定上意见相反 |
| 信任校准 | 对方说了一句你不确定是不是开玩笑的话 |
| 情绪回应 | 你努力准备的东西被否定了 |
| 身份边界 | 对方要求你改变一个你很看重的习惯 |

系统从选择中**反推**决策逻辑，而不是相信自我描述。推断结果反馈进信念图谱，形成闭环。

初始化题库不是随便拼的“恋爱问答”，而是按几个稳定的人格与关系心理学构念来设计：

- **成人依恋**：参考 ECR / ECR-R 这类研究常用的依恋焦虑、依恋回避维度，观察一个人在冲突后追问、抽离、安抚需求、信任修复上的偏好
- **情绪调节**：参考 emotion regulation 与 couples interpersonal emotion regulation 研究，看一个人在受伤、被否定、被误解时是解释、沉默、冷处理，还是主动寻求修复
- **价值权衡 / 道德取舍**：参考 moral trade-off / dilemma judgment 相关研究，不只看“选哪个”，更看如何在忠诚、公平、伤害控制、关系承诺之间做平衡
- **身份边界与自主性**：参考 self-determination / boundary regulation 的思路，观察一个人在亲密关系里何时愿意妥协，何时会觉得“再退一步就不像我了”
- **目标层级与代价承受**：借鉴 social-cognitive personality signatures / goal hierarchy 的思路，关注一个人在事业、关系、自由、家庭期待之间如何排序，以及愿意承担什么代价

心译没有把论文量表题直接搬进 UI，也没有把用户当成在做心理测验。更接近的做法是：

1. 用论文里比较稳定的心理构念做题目“骨架”
2. 改写成日常关系里能自然回答的情境题
3. 通过回答内容反推这个人的 if-then 模式，而不是只记一个标签

当前默认初始化题主要参考过这些方向：

- Brennan, Clark, Shaver 的 **Experiences in Close Relationships (ECR)** / 后续 ECR-R 体系，用于依恋焦虑与依恋回避
- Mikulincer & Shaver 关于 **adult romantic attachment**、亲密关系中的安全感与调节模式
- couples **interpersonal emotion regulation** 方向的研究，用于设计“受伤后如何修复 / 需要怎样被安抚”这类题
- **moral trade-off / dilemma judgment** 相关研究，用于设计必须在冲突价值之间取舍的任务
- social-cognitive personality signatures / goal hierarchy 的思路，用于设计“长期优先级 / 代价承受”类题

所以，校准的目标不是给用户贴一个“你是某某型人格”的标签，而是让系统逐渐学到：

- 在什么场景下，你会先追问还是先退开
- 在什么边界上，你会妥协，什么地方不会
- 当关系、安全感、尊严、现实利益冲突时，你通常怎么排序

### 6. 关系报告 & 分身诊断

- **关系报告**：自动生成双方沟通模式、情感结构、信任度分析
- **分身诊断**：向分身提问，评估思维模式还原度（70%权重）和语气一致性（30%权重），给出是否需要继续校准的建议

---

## 技术架构

```
微信加密数据库
    ↓ SQLCipher 解密（内存密钥提取）
原始消息
    ↓ 清洗（去系统消息、PII 脱敏、群聊过滤）
    ↓ 按训练模式筛选（你的消息 or TA 的消息）
对话片段
    ↓ 情感感知分块（可选，给 chunk 打上情绪标签）
    ↓ 按情境分桶 + 向量化
    ├── ChromaDB 向量记忆（对话检索 + 重排 + few-shot 采样）
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

**关键模型**（全部 CPU 可跑，无需显卡）：

| 用途 | 模型 | 大小 | 推理耗时 |
|------|------|------|---------|
| 向量化 | shibing624/text2vec-base-chinese | ~400MB | ~50ms/次 |
| 重排（可选） | BAAI/bge-reranker-base | ~400MB | ~100ms/次 |
| 情感分类（可选） | Johnson8187/Chinese-Emotion-Small | ~1.1GB | <100ms/chunk |

---

## 工程化与近期迭代

在保持核心能力不变的前提下，持续改进可维护性、体验与打包分发：

| 模块 | 改动 | 说明 |
|------|------|------|
| Tab 模块化 | `src/ui/tabs/` | UI 按功能页拆分；`app.py` 仍承担组装与全局状态 |
| 日志体系 | `src/logging_config.py` | 结构化日志，可落盘 |
| 异常与提示 | `src/exceptions.py`、`src/ui/ux_helpers.py` | 语义化异常 + 统一错误/进度卡片；对话流式失败带重试提示 |
| 测试 | `tests/`（pytest） | 清洗、检索、嵌入、信念图、异常等单元测试 |
| 配置 | `src/config.py` + `config.yaml` | Pydantic 校验；支持 `XINYI_ENV` 等环境开关 |
| 隐私脱敏 | `src/data/privacy_redactor.py` | 手机号、证件号等可配置脱敏规则 |
| API 热重载 | 设置页保存 | 保存 API 配置后自动重建 OpenAI/Anthropic 客户端与顾问引擎 |
| 小模型 | `reranker`、`emotion_tagger` | 重排与可选情感分块，训练/检索阶段接入 |
| 校准与信念 | `cognitive/`、`belief/` | 默认情境题库 + 矛盾检测与追问；信念支持手动编辑 |
| 打包 | PyInstaller、`xinyi.spec` / `xinyi-windows.spec` | 安装包在可写目录生成 `config.yaml`/`data/`；启动时 `inbrowser` 打开控制台 |
| CI | `.github/workflows/build.yml` | push `main` 构建 macOS/Windows _zip 并更新 Release（需配置 `GH_TOKEN` Secret） |

---

## 平台支持

| 平台 | 数据解密 | 说明 |
|------|---------|------|
| macOS | ✅ 全自动 | 首次需 ad-hoc 重签微信 |
| Windows 10/11 | ✅ 全自动 | 需管理员终端启动 |

支持微信 4.x（SQLCipher 4 加密）。

---

## 隐私与数据安全

- **所有数据本地存储**，不上传到任何服务器
- 训练数据、向量库、人格画像全部在 `data/` 目录，删掉即清空
- `.env` 和 `config.yaml` 不被 git 提交，API Key 不会泄露

**什么数据会发送给 API 服务商？**

| 场景 | 发送内容 | 不发送 |
|------|---------|--------|
| 训练阶段 | 对话片段原文（分批，每次数十条）用于人格分析、信念提取、记忆提取 | 一次性发送完整聊天记录 |
| 对话阶段 | 当前对话上下文 + 向量检索到的相关对话片段 + 真实聊天记录样本（few-shot） | 向量库全量数据 |
| 分析/报告 | 采样对话片段 + 统计摘要 | 原始数据库文件 |

训练和对话过程中会将**真实聊天记录片段**发送给 API 用于分析和风格模仿，这是核心功能所必需的。系统已自动脱敏手机号、身份证号、邮箱地址，但聊天中的**姓名、地址、公司名**等自然语言信息无法完全自动识别，仍可能包含在发送内容中。

**如需完全离线**，可在 `config.yaml` 中配置 Ollama 或 vLLM 等本地推理服务（需 OpenAI 兼容格式），所有数据完全不离开本机。

---

## 重要声明

- 本工具**仅供用户操作本人微信账号的数据**。请勿用于获取、解密或分析他人账号数据。
- 解密过程涉及读取微信进程内存中的加密密钥和 ad-hoc 重签名（macOS），使用前请知悉相关技术风险。
- 项目仅用于个人学习和研究目的。开发者不对任何滥用行为承担责任。
- 使用本工具即表示你已理解上述声明，并自行承担使用风险。

---

## 常见问题（FAQ）

### 安装与运行

**Q：安装包和源码运行有什么区别？**  
A：安装包内置 Python 与依赖，双击即可；**只有源码环境**能在本机完成微信解密（Windows 还需管理员终端）。Docker 不解密。

**Q：控制台地址不是 7872 怎么办？**  
A：默认 Gradio 使用 **7872**；若端口被占用，日志里会打印实际端口。安装包与 `python -m src` 均在启动时尝试 **`inbrowser` 自动打开浏览器**；若被系统拦截，请手动访问日志中的 URL。

**Q：macOS 把 app 丢进「应用程序」后，配置写到哪里？**  
A：若 `/Applications` 下对当前用户**不可写**，程序会退回到 **`~/Library/Application Support/xinyi`** 存放 `config.yaml` 与 `data/`。若 app 在桌面/下载目录等可写位置旁，则通常写在 **与 `.app` 同级的文件夹**。

**Q：对话时一直转圈或很久才出字？**  
A：首次调用会拉模型、建向量索引；对话走 **流式输出**，中间可能出现「思考 / 检索 / 重试」类提示。若连续失败，界面会提示检查 **API Key 与网络**；也可打开 **「系统」Tab** 看连接状态。

### 数据与训练

**Q：支持哪些大模型 API？**  
A：**OpenAI 兼容**（官方 OpenAI、多数国内中转）与 **Anthropic**（需在配置里选对 `provider`）。DeepSeek、硅基流动等只要兼容 OpenAI 的 `base_url` + Key 即可。

**Q：大概要多少条聊天才有效果？**  
A：至少约 **30 条**有效双人对话；**300+** 更明显，**1000+** 趋于稳定。具体因话题多样性而异。

**Q：「训练自己」和「训练对象」能同时启用吗？**  
A：**一次只能一种**主模式。想两种都试，可用两套目录（两份安装文件夹或两份克隆仓库）分别训练。

**Q：会动我的微信数据吗？**  
A：解密阶段**只读**进程内存中的密钥并解密本地库副本，**不修改**微信客户端行为与官方数据文件（仍建议备份）。

**Q：Docker 里能解密微信吗？**  
A：**不能**。容器内无法完成本机微信内存解密，请用源码方式解密后再挂载 `data/`。

### 合规与隐私

**Q：聊天记录会传到你们服务器吗？**  
A：**不会**。数据在本地 `data/`；与**你配置的 API 服务商**之间的请求见上文「隐私与数据安全」表格。

---

## 故障排除

按现象自查（仍无法解决时，可带 **日志片段** 与系统版本提 Issue）。

| 现象 | 可能原因 | 建议操作 |
|------|----------|----------|
| 白屏 / 无法打开网页 | 进程未起来或端口错误 | 看控制台/终端日志；换浏览器访问 `http://127.0.0.1:7872`；检查防火墙是否拦截本地端口 |
| `Address already in use` / 端口占用 | 7872 已被占用 | 关闭旧的心译进程或其它占用程序；或改 `config`/启动参数中的端口（若你有自定义） |
| `Access Denied`（Windows） | 解密需要提权 | **管理员** PowerShell 再运行 `python -m src` |
| `task_for_pid failed`（macOS） | SIP / 权限未按向导配置 | 在应用内 **「连接 / 设置」** 跟提示完成微信侧步骤；必要时查阅项目 `docs` 与 decrypt 工具说明 |
| 找不到 `config.yaml` | 工作目录不对或首次未生成 | 源码方式请在**项目根**执行命令；安装包查看 **`.app` 同级** 或 **`~/Library/Application Support/xinyi`** |
| 嵌入模型下载极慢 / 超时 | HuggingFace 网络问题 | 终端执行 `export HF_ENDPOINT=https://hf-mirror.com` 后重启；或预先下载模型到本机并在 `config.yaml` 指定路径 |
| ChromaDB / 权限错误 | `data/` 不可写或损坏 | 确认目录权限；可备份后删除 `data/chroma_db` 再重新训练（会丢失向量索引，需重跑学习流程） |
| API 401 / Invalid Key | Key 错误或 `base_url` 不匹配 | 在 **设置** 中重填 Key；中转站需填对 **完整 base_url**（常以 `/v1` 结尾视服务商而定） |
| 对话报错「不支持的 provider」 | `config.yaml` 里 `api.provider` 与客户端不一致 | 流式对话当前支持 **openai / gemini（走 OpenAI 兼容接口时）/ anthropic**；请改 `provider` 或换兼容网关 |
| Release 无新包 / CI 红 | 仓库未配置 Secret 或构建失败 | 维护者需在 GitHub **Settings → Secrets** 配置 **`GH_TOKEN`**（`contents: write`）；在 **Actions** 页查看失败 job 日志 |

**日志位置**：源码运行时日志多在**启动终端**；`config.yaml` 中可配置 `logging.dir`（默认 `logs/`）。Windows 安装包会保留**控制台窗口**便于复制报错。

---

## 开发者参考：配置与模块说明

本仓库**没有**对外公开的 HTTP REST API；「API」主要指 **大模型服务商的 API**（通过 `config.yaml` 的 `api` 段配置）。界面由 **Gradio** 在本地起服务，浏览器访问即可。

### `config.yaml` 中与「API」相关的键（概念说明）

| 键 / 段 | 作用 |
|---------|------|
| `api.provider` | `openai` 或 `anthropic` 等，影响底层 SDK 与流式实现 |
| `api.api_key` / `api.base_url` | 密钥与兼容网关地址（可为空表示官方默认） |
| `api.model` | 对话主模型名 |
| `api.headers` | 部分中转需要的额外 HTTP 头 |
| `embedding` / `rerank` / `emotion` | 本地小模型名称与设备（CPU/CUDA） |

环境变量支持在 YAML 中写 `${VAR:默认值}`；`.env` 由 `python-dotenv` 加载（见 `src/config.py`、`src/app.load_config`）。

### `src/` 目录职责速查（便于读代码）

| 路径 | 职责 |
|------|------|
| `src/__main__.py` | 入口：`load_config` → `build_ui` → `launch(inbrowser=True)` |
| `src/app.py` | Gradio 总装：全局状态、`init_components`、`build_ui`、业务回调（体量最大） |
| `src/config.py` | Pydantic 配置模型与 `load_config` / `get_config` |
| `src/exceptions.py` | 业务异常类型与 `exc_to_user_msg` / `exc_to_actionable_msg` |
| `src/logging_config.py` | 日志初始化 |
| `src/engine/chat.py` | 主对话引擎：检索、内心独白、**流式**回复与重试 |
| `src/engine/training.py`、`learning.py` | 训练流水线与学习循环 |
| `src/engine/partner_advisor.py` | 关系顾问 @KK、流式接口 |
| `src/engine/advisor_registry.py` | 顾问 / 调解器实例注册与热重载 |
| `src/engine/session.py` | 会话管理 |
| `src/mediation/mediator.py` | 冲突调解对话逻辑 |
| `src/memory/*` | 嵌入、Chroma 向量库、检索、重排、MemoryBank、multi_md 多路记忆 |
| `src/belief/*` | 信念抽取、图谱、矛盾检测 |
| `src/personality/*` | 提示词组装、情绪跟踪、思维画像、引导文案 |
| `src/data/*` | 微信解析、清洗、解密、分块、脱敏、`partner_config` |
| `src/cognitive/*` | 校准任务库、主动探测、推理 |
| `src/eval/evaluator.py` | 分身诊断评分 |
| `src/features/*` | 冷却期、预发送、报告、本地模型预设、FTUE 等 |
| `src/ui/tabs/*` | 各功能 Tab；`ux_helpers.py` / `styles.py` 为统一 UI 片段与样式 |
| `src/ui/callbacks_api.py` | 设置页读写 `config.yaml`、保存后触发 `init_components` 与 registry 重载 |

更细的接口以代码为准；欢迎通过 PR 补充 **docstring** 或 `docs/` 下的专题文档。

---

## 致谢

- [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) — 微信 4.x 三端数据库解密方案
