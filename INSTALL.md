# xinyi 傻瓜安装指南

> 支持 macOS / Windows / Linux，下载 → 解压 → 双击即可运行。

---

## 下载安装包

进入 [Releases 页面](https://github.com/kroxchan/xinyi/releases) 下载对应版本：

| 操作系统 | 下载文件 | 说明 |
|----------|----------|------|
| macOS (Apple 芯片 / Intel) | `xinyi-macos.zip` | 双击解压，双击 `xinyi.app` |
| Windows | `xinyi-windows.zip` | 右键解压，运行 `xinyi.exe` |
| Linux | `xinyi-linux.tar.gz` | 解压后运行 `./xinyi` |

---

## 第一步：解压

**macOS:**
双击 `xinyi-macos.zip` → 得到 `xinyi.app` → 双击打开

**Windows:**
右键 `xinyi-windows.zip` → 解压到当前文件夹 → 双击 `xinyi.exe`

**Linux:**
```bash
tar -xzf xinyi-linux.tar.gz
./xinyi
```

> 首次打开时 macOS 会提示"无法打开，因为来自身份不明的开发者"，
> 解决方法：系统偏好设置 → 安全性与隐私 → 仍要打开

---

## 第二步：填写 API Key

xinyi 支持 **OpenAI / Anthropic / 所有 OpenAI 兼容接口**（如硅基流动、火山引擎等）。

打开界面后（浏览器访问 `http://localhost:7872` 或 app 窗口），
找到 **设置 / Config** 标签页，填入：

| 字段 | 示例值 |
|------|--------|
| API Key | `sk-your-key-here` |
| 模型 | `gpt-4o`（可选，默认 gpt-4o） |
| Base URL | 使用 OpenAI 官方留空；自建代理填入地址 |

按 **保存**，即可开始使用。

---

## 第三步：导入聊天记录（可选）

进入 **导入数据** 标签页，按提示操作：
1. 准备好微信导出文件
2. 解密 → 训练
3. 训练完成后即可与 AI 分身对话

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `xinyi.app` / `xinyi.exe` / `xinyi` | 主程序，双击运行 |
| `data/` | 聊天记录和训练数据（运行后自动生成） |
| `config.yaml` | 配置文件（首次保存 API Key 后生成） |
| `.env` | API Key（可选，也可直接在界面填写） |

---

## 命令行安装（适合开发者）

```bash
# 一行安装
bash <(curl -fsSL https://raw.githubusercontent.com/kroxchan/xinyi/main/scripts/install.sh)

# 启动
./run.sh
```

---

## 常见问题

**Q: macOS 提示"无法打开"？**
> 系统偏好设置 → 安全性与隐私 → 仍要打开

**Q: 提示"找不到 Python"？**
> 需要 Python 3.10+，推荐 [python.org/downloads](https://www.python.org/downloads/)

**Q: 首次运行很慢？**
> 首次会下载 AI 模型（约 500MB），耐心等待即可，后续无需重复下载

**Q: 端口被占用？**
> xinyi 默认使用 7872 端口，修改 `config.yaml` 中的 `server_port` 即可

**Q: 想卸载？**
> 删除整个 xinyi 文件夹即可，无残留

**Q: 聊天记录存在哪里？**
> 本地 `data/` 目录，不会上传到任何服务器
