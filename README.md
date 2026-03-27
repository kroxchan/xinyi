# 心译

> 发出去之前，先译一下。

基于真实微信聊天记录的关系理解工具。学会 TA（或你自己）的说话方式，帮你在发消息前「译」一下——更准确地表达，更真实地理解。

## 快速开始

### 第一步：环境准备

- Python 3.10 或以上
- 一个 OpenAI 兼容的 API Key（OpenAI / Claude / DeepSeek / 国内中转均可）

```bash
# 克隆项目
git clone https://github.com/你的用户名/wechat-twin-partner.git
cd wechat-twin-partner

# 安装依赖
pip install -r requirements.txt
```

> Windows 用户：如遇权限问题，改用 `pip install --user -r requirements.txt`

### 第二步：配置 API

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入你的 API 信息：

```yaml
api:
  api_key: "sk-xxxx"          # 你的 API Key
  base_url: "https://..."     # 非 OpenAI 官方时填入，否则可删除此行
  model: "gpt-4o"             # 使用的模型名
```

或者用 `.env` 文件（更安全，不会被 git 提交）：

```bash
echo "WECHAT_TWIN_API_KEY=sk-xxxx" > .env
echo "WECHAT_TWIN_BASE_URL=https://..." >> .env   # 可选
echo "WECHAT_TWIN_MODEL=gpt-4o" >> .env           # 可选
```

### 第三步：启动

```bash
# macOS / Linux
python src/app.py

# Windows（需管理员终端）
# Win+X → "Windows PowerShell（管理员）" → cd 到项目目录 → 运行：
python src/app.py
```

浏览器会自动打开，或手动访问 **http://localhost:7872**

---

## 应用内向导

启动后按向导走，大约 5-10 分钟完成设置：

| 步骤 | 做什么 |
|------|--------|
| **连接** | 填入 API Key，测试连通性 |
| **选择 TA** | 扫描联系人，选择你想建立分身的那个人 |
| **学习** | 一键解密微信数据库 → 读取聊天记录 → 训练分身 |
| **心译对话** | 开始对话（学习完成后自动解锁） |

> 至少需要与对方约 **30 条以上**的有效聊天记录，越多越准。

---

## 平台支持

| 平台 | 数据解密 | 说明 |
|------|---------|------|
| macOS | ✅ 全自动 | 向导内一键完成，首次需要 ad-hoc 重签微信 |
| Windows 10/11 | ✅ 全自动 | 需以**管理员身份**启动程序（见上方启动说明） |
| Linux | ✅ 全自动 | 需 root 权限或 `CAP_SYS_PTRACE` |

解密方案基于 [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)，支持微信 4.x SQLCipher 加密数据库，已内置于 `vendor/` 目录，无需单独安装。

---

## 功能一览

- **心译对话**：个人模式（用你的语气）/ 对象模式（用 TA 的语气）；输入 `@KK` 获得关系洞察
- **关系报告**：自动生成情感结构、信任度、沟通模式分析
- **分身诊断**：评估分身还原度（思维模式 70% + 语气 30%），给出是否继续校准的建议
- **人格校准**：通过情境任务（非问卷）细化分身的认知模型
- **数据洞察 / 内心地图 / 记忆**：可按需使用

---

## 常见问题

**Q：支持哪些 API？**
OpenAI、Anthropic、DeepSeek，以及所有兼容 OpenAI 格式的国内中转服务均可。

**Q：数据安全吗？**
所有数据本地存储，不上传到任何服务器。API 调用内容仅包含聊天记录摘要，不包含原始完整记录。

**Q：微信解密会影响我的微信吗？**
macOS 首次需要对微信做 ad-hoc 重签（去掉 Hardened Runtime 限制），向导内自动完成。不影响微信功能，仅允许内存读取。

**Q：提示「task_for_pid failed」（macOS）**
需要临时调整 SIP 设置，向导的「连接」页有详细步骤说明。

**Q：提示「Access Denied」（Windows）**
没有用管理员终端启动程序，参考上方「启动」说明。

---

## 致谢

- [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) — 微信 4.x 三端数据库解密方案
