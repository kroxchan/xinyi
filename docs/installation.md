# 安装与运行

本文档是 [README](../README.md) 中安装部分的详细展开，涵盖所有三种安装方式与故障排除。

---

## 选择安装方式

| 方式 | 需要 Python | 支持微信解密 | 适合人群 |
|------|------------|------------|---------|
| **安装包** | ❌ | ❌ | 不想装 Python，只想快速体验 |
| **源码** | ✅ | ✅ | 需要解密本机微信，深入定制 |
| **Docker** | ❌ | ❌ | 已有解密好的 `data/`，完全不想装环境 |

---

## 方式一：安装包（macOS / Windows）

> 适合绝大多数用户：无需 Python，双击运行。

### 下载

👉 [Releases 下载最新版](https://github.com/kroxchan/xinyi/releases/latest)

| 系统 | 文件 | 运行方式 |
|------|------|---------|
| macOS | `xinyi-macos.zip` | 解压后双击 `xinyi.app` |
| Windows | `xinyi-windows.zip` | 解压后双击 `xinyi.exe`（会保留黑色控制台窗口，请勿关闭）|

**macOS 首次打开提示"无法打开，因为来自身份不明的开发者"？**  
系统设置 → 隐私与安全性 → 滚动到下方 → 点击"**仍要打开**"

### 配置 API Key

首次运行后，会自动在**可写目录**生成 `config.yaml`：

- macOS：与 `.app` 同级的文件夹；若无写权限则退回到 `~/Library/Application Support/xinyi`
- Windows：解压目录

打开应用，在 **设置** Tab 中填入 API Key 并保存：

| 字段 | 说明 |
|------|------|
| API Key | 你的 OpenAI / Anthropic / 兼容接口 Key |
| 模型 | 留空默认 `gpt-4o` |
| Base URL | 使用 OpenAI 官方留空；硅基流动/火山引擎等填入代理地址 |

### 访问控制台

启动后应用会**自动尝试打开浏览器**访问 `http://127.0.0.1:7872`。若未弹出，手动在浏览器输入该地址即可。

---

## 方式二：源码安装

> 最稳定，且支持微信内存解密。Windows 需管理员终端。

### 环境要求

- Python **3.10+**
- macOS / Windows / Linux
- 任意 **OpenAI 兼容** API（OpenAI、Anthropic、DeepSeek、硅基流动等）

### 安装步骤

```bash
git clone https://github.com/kroxchan/xinyi.git
cd xinyi
pip install -r requirements.txt
```

### 配置

```bash
# 方式 A：.env 文件（推荐，密钥不写进配置文件）
cp .env.example .env
# 编辑 .env，填入 API Key

# 方式 B：直接编辑 config.yaml
cp config.default.yaml config.yaml
# 编辑 config.yaml：api_key、base_url、model 等
```

> `.env` 与 `config.yaml` 均在 `.gitignore` 中，不会被提交。

### 启动

```bash
# 推荐（与 run.sh 一致）
python -m src

# 或
python src/app.py
```

浏览器访问 **http://localhost:7872**（或日志里打印的地址）。

### 加速模型下载（国内用户）

首次训练会自动下载嵌入 / 重排 / 情感等模型（Hugging Face 下载慢）：

```bash
export HF_ENDPOINT=https://hf-mirror.com
python -m src
```

### Windows 解密

需 **管理员** 终端（Win+X → PowerShell 管理员）再运行上述命令。

---

## 方式三：Docker

> 容器内**无法**完成微信内存解密。仅适合已有处理好的 `data/` 或使用外部解密流程的用户。

### 构建并运行

```bash
docker build -t xinyi .
docker run -it -p 7872:7872 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/data:/app/data \
  xinyi
```

### docker-compose（推荐）

```bash
cp config.default.yaml config.yaml
# 编辑 config.yaml 填入 API Key
docker-compose up
```

---

## 故障排除

| 现象 | 可能原因 | 建议操作 |
|------|----------|---------|
| 白屏 / 无法打开网页 | 进程未起来或端口错误 | 看控制台/终端日志；换浏览器访问 `http://127.0.0.1:7872`；检查防火墙是否拦截本地端口 |
| `Address already in use` | 7872 已被占用 | 关闭旧的心译进程或其它占用程序 |
| `Access Denied`（Windows） | 解密需要提权 | **管理员** PowerShell 再运行 `python -m src` |
| `task_for_pid failed`（macOS） | SIP / 权限未配置 | 在应用内 **连接** Tab 跟提示完成微信侧步骤 |
| 找不到 `config.yaml` | 工作目录不对或首次未生成 | 源码在**项目根**执行；安装包查看 **`.app` 同级** 或 **`~/Library/Application Support/xinyi`** |
| 模型下载极慢 / 超时 | HuggingFace 网络问题 | `export HF_ENDPOINT=https://hf-mirror.com` 后重启 |
| ChromaDB / 权限错误 | `data/` 不可写或损坏 | 确认目录权限；备份后删除 `data/chroma_db` 再重新训练 |
| API 401 / Invalid Key | Key 错误或 `base_url` 不匹配 | 在 **设置** 中重填 Key；中转站需填对 **完整 base_url**（常以 `/v1` 结尾） |
| 对话报错「不支持的 provider」 | `config.yaml` 里 `provider` 与客户端不一致 | 当前支持 **openai / anthropic / gemini（走 OpenAI 兼容接口时）** |

**日志位置**：源码运行时日志在**启动终端**；`config.yaml` 中可配置 `logging.dir`（默认 `logs/`）。Windows 安装包会保留**控制台窗口**便于复制报错。

---

## 文件说明（安装包）

| 文件 / 目录 | 作用 |
|------------|------|
| `xinyi.app` / `xinyi.exe` | 主程序，双击运行 |
| `data/` | 聊天记录和训练数据（运行后自动生成） |
| `config.yaml` | 配置文件（首次保存后生成） |
| `logs/` | 运行日志（`config.yaml` 中 `logging.dir` 控制） |
