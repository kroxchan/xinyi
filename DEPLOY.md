# xinyi 部署指南

## 方式一：原生 macOS/Linux 环境（推荐，需要微信解密时使用）

### 前置要求

- Python 3.11+
- Xcode Command Line Tools（macOS 用于微信数据库解密）
- 已解密的微信数据库文件

### 步骤

1. **克隆项目**

```bash
git clone <repo-url>
cd xinyi
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **下载小模型（首次运行前建议执行，避免卡顿）**

```bash
bash scripts/init_models.sh
```

4. **配置 API Key**

```bash
cp .env.example .env
# 编辑 .env，填入 WECHAT_TWIN_API_KEY 和 WECHAT_TWIN_BASE_URL
```

5. **配置 config.yaml**

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml（如需要）
```

6. **启动**

```bash
python src/app.py
```

访问 `http://localhost:7872`

---

## 方式二：Docker 环境（无需 Python 环境，适合已有解密数据的用户）

### 前置要求

- Docker 24+
- docker-compose v2+
- 已解密的微信数据库文件在 `data/raw/` 目录

### 步骤

1. **克隆项目**

```bash
git clone <repo-url>
cd xinyi
```

2. **准备数据目录**

将已解密的 `.db` 文件放入 `data/raw/`：

```
data/raw/
├── message/message_0.db
├── contact/contact.db
└── ...
```

3. **配置环境变量**

```bash
cp .env.example .env
# 编辑 .env
```

4. **构建并启动**

```bash
docker compose up --build
```

访问 `http://localhost:7872`

### 可选：启用外部 ChromaDB

```bash
docker compose --profile with-chroma up --build
```

### 停止

```bash
docker compose down
```

---

## 环境模式切换

| 变量 | 值 | 效果 |
|------|----|------|
| `XINYI_ENV` | `dev` | 日志 DEBUG 级，支持热重载 |
| `XINYI_ENV` | `prod` | 日志 INFO 级，默认值 |

---

## 注意事项

- **微信解密**：只有原生 macOS 环境支持微信数据库解密。Docker 容器内无法解密。
- **GPU 加速**：当前版本所有模型（嵌入/rerank/情感分类）均为 CPU 可跑，不依赖显卡。
- **模型下载**：首次运行时自动下载模型（约 1.1GB），可提前用 `scripts/init_models.sh` 预下载。
- **数据持久化**：Docker 模式下，`data/` 目录通过卷挂载持久化，重启不丢失。

---

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 启动报错 `Module not found` | `pip install -r requirements.txt` |
| 模型加载慢/卡住 | 运行 `bash scripts/init_models.sh` 预下载 |
| API Key 无效 | 检查 `.env` 中的 `WECHAT_TWIN_API_KEY` |
| Docker 端口冲突 | 修改 `docker-compose.yml` 中的 `7872` 端口映射 |
| ChromaDB 连接失败 | 确认使用 `USE_EXTERNAL_CHROMA=0` 或启用外部 ChromaDB |
