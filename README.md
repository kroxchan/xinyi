# 心译

> 发出去之前，先译一下。

读真实微信聊天记录，构建一个说话方式和思维模式都接近真人的 AI「数字分身」。

- **训练自己**：学你的说话风格，对象可以和「你的分身」聊，看你平时怎么表达的
- **训练对方**：学 TA 的说话风格，你可以和「TA 的分身」对话，理解 TA 为什么那样说
  
![img_v3_0210a_3e5db79c-4e7a-4b21-bb52-bf4aa3eca65g](https://github.com/user-attachments/assets/d23784ff-949e-410d-82ec-69fa70775c18)

---

## 🎯 快速链接

| 想做什么 | 往哪走 |
|---------|--------|
| 想快速试用？ | [下载安装包](https://github.com/kroxchan/xinyi/releases/latest) |
| 想深入理解原理？ | [技术架构文档](docs/architecture.md) |
| 想贡献代码？ | [贡献指南](CONTRIBUTING.md) |
| 想讨论想法？ | [GitHub Discussions](https://github.com/kroxchan/xinyi/discussions) |
| 找到 Bug 了？ | [提交 Issue](https://github.com/kroxchan/xinyi/issues) |
| 想要新功能？ | [去 Discussions 建议](https://github.com/kroxchan/xinyi/discussions) |

---

## 界面功能一览

应用有 **8 个标签页**，涵盖从数据接入到深度分析的完整流程：

| Tab | 功能 |
|-----|------|
| **连接** | 配置 API、解密微信、选聊天对象、选训练模式、开始学习 |
| **心译对话** | 与分身聊天；输入 `@KK` 召唤关系顾问 |
| **关系报告** | 全景关系分析：沟通模式、情感结构、信任度等 |
| **校准** | 情境题反推决策逻辑，细化人格模型 |
| **数据洞察** | 消息统计、联系人分布、时间分布等 |
| **内心地图** | 信念图谱：查看和搜索已抽取的立场条目 |
| **记忆** | 管理从聊天中抽取的结构化事实 |
| **设置** | API 配置、模型状态、系统信息 |

完整图文说明：[使用说明](docs/使用说明.md)

---

## 安装与运行

> 详细图文步骤：[安装文档](docs/installation.md)

### 安装包（macOS / Windows）

无需 Python，双击即用。

👉 [Releases 下载](https://github.com/kroxchan/xinyi/releases/latest)

| 系统 | 下载文件 |
|------|---------|
| macOS | `xinyi-macos.zip` → 双击 `xinyi.app` |
| Windows | `xinyi-windows.zip` → 双击 `xinyi.exe` |

首次运行会自动在可写目录生成 `config.yaml`；在 **设置** 填入 API Key 保存即可。

### 源码安装（支持微信解密）

```bash
git clone https://github.com/kroxchan/xinyi.git
cd xinyi
pip install -r requirements.txt
cp .env.example .env          # 填入 API Key
python -m src                 # 启动
# 浏览器访问 http://localhost:7872
```

Windows 解密需**管理员**终端运行。

### Docker（不解密微信）

已有处理好的 `data/`？直接挂载使用：

```bash
docker build -t xinyi .
docker run -it -p 7872:7872 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/data:/app/data \
  xinyi
```

---

## 两种训练模式

| 模式 | 学谁的消息 | 谁来对话 | 典型用法 |
|------|-----------|---------|---------|
| 训练自己 | 你发出的消息 | 对象和分身聊 | 练习表达、回顾自己的沟通模式 |
| 训练对象 | TA 发出的消息 | 你和分身聊 | 理解 TA 的想法、预测 TA 会怎么回 |

选好后一键学习，后续所有功能（对话、报告、校准）都基于这个选择。

---

## 核心能力

**对话引擎** — 先想，再说
每次回复前先做认知评估（情绪状态、分身第一反应、心理背景），再生成回复。语气来自向量库中真实说过的话，不是手写示例。

**信念图谱** — 抽出来的不是关键词，是立场
「关于道歉：倾向于先冷静再处理，而不是当场解决」。信念参与每次对话，不是装饰。

**情绪状态机** — 情绪有惯性，有传染，有阈值
不会上一句还在生气，下一句突然温柔。负面情绪衰减比正面慢。

**认知校准** — 用情境题反推决策逻辑
不做性格测试，从「你选了什么」反推你在冲突、信任、边界等场景下的真实决策规则。

> 完整能力说明：[技术架构文档](docs/architecture.md)

---

## 隐私与数据安全

- **所有数据本地存储**，不上传到任何服务器
- 删掉 `data/` 即清空
- API Key 不被 git 提交
- 部分对话片段发送给配置的 API 服务商用于分析；已自动脱敏手机号、证件号、邮箱
- 完全离线：配置 Ollama 或 vLLM（OpenAI 兼容格式）即可

> 完整隐私说明：[隐私文档](docs/privacy.md)

---

## 平台支持

| 平台 | 数据解密 | 说明 |
|------|---------|------|
| macOS | ✅ 全自动 | 首次需 ad-hoc 重签微信 |
| Windows 10/11 | ✅ 全自动 | 需管理员终端启动 |

支持微信 4.x（SQLCipher 4 加密）。

---

## 常见问题

**Q：控制台打不开？**  
A：默认 `http://127.0.0.1:7872`；若端口被占用，日志里会打印实际地址。也可打开 **设置** 查看连接状态。

**Q：一直转圈或很久才出字？**  
A：首次调用会拉模型，建向量索引。连续失败请检查 **API Key 与网络**；打开 **设置** 看连接状态。

**Q：需要多少条聊天？**  
A：约 **30 条**起步，**300+** 效果明显，**1000+** 趋于稳定。

**Q：Docker 能解密微信吗？**  
A：**不能**，容器无法访问本机微信内存。用源码方式解密后再挂载 `data/`。

完整 FAQ 与故障排除：[使用说明 → FAQ](docs/使用说明.md#常见问题)

---

## 💝 致谢

**wechat-decrypt 团队** — [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)  
微信 4.x 三端数据库解密方案，让心译能安全读取本地聊天记录。

---

## 📜 License

MIT License — 自由使用、修改、商业化

---

## ⭐ 觉得有帮助？

给个 **Star** ⭐ 支持一下！

它帮助项目被更多人发现。如果你觉得这个想法值得存在，你的 Star 就是最好的认可。

---

## 🔗 链接

| 平台 | 地址 |
|------|------|
| GitHub | https://github.com/kroxchan/xinyi |
| Issues | https://github.com/kroxchan/xinyi/issues |
| Discussions | https://github.com/kroxchan/xinyi/discussions |
| Twitter | [@kroxchan_32611](https://twitter.com/kroxchan_32611) |

## 📞 需要帮助？

- 💬 [GitHub Discussions](https://github.com/kroxchan/xinyi/discussions) — 讨论想法
- 🐛 [GitHub Issues](https://github.com/kroxchan/xinyi/issues) — 报告 Bug
- 📧 Email
- 🐦 [Twitter: @kroxchan_32611](https://twitter.com/kroxchan_32611)

---

Made ❤️ by [@kroxchan](https://github.com/kroxchan)
