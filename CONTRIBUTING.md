# 贡献指南

感谢你愿意为心译贡献代码！本文档帮助你快速上手。

> 遇到问题？去 [GitHub Discussions](https://github.com/kroxchan/xinyi/discussions) 聊聊。

---

## 开发环境快速上手

### 1. 克隆代码

```bash
git clone https://github.com/kroxchan/xinyi.git
cd xinyi
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 填入你的 API Key
```

### 4. 启动开发版

```bash
python -m src
# 浏览器访问 http://localhost:7872
```

### 5. 运行测试

```bash
pytest tests/ -v
```

---

## 代码规范

- Python：遵循 `black` + `isort` 格式化
- Git commit message：使用中文，格式建议 `[模块] 简短描述`
- 新增功能请同步补充 docstring；新增用户可见功能请同步更新文档

---

## 项目结构速查

```
src/
├── app.py                # Gradio 总装（入口最重）
├── config.py             # Pydantic 配置层
├── engine/               # 对话引擎、训练流水线
├── memory/               # ChromaDB、BM25、MemoryBank
├── belief/               # 信念图谱
├── personality/          # 思维画像、情绪
├── cognitive/            # 认知校准题库
├── data/                 # 微信解析、清洗、解密
├── eval/                 # 分身诊断
├── ui/tabs/              # 各 Tab 组件
└── ...
tests/                    # pytest 单元测试
docs/                     # 文档
```

---

## 提 Pull Request 前的检查清单

- [ ] 代码格式正确（`black . && isort .`）
- [ ] `pytest tests/` 全部通过
- [ ] 新依赖已添加到 `requirements.txt` / `pyproject.toml`
- [ ] 文档已同步更新（如适用）
- [ ] Commit message 清晰说明改动内容

---

## 提交 Bug 或功能建议

- **Bug**：请附上复现步骤、系统版本、错误日志片段
- **功能建议**：欢迎去 [Discussions](https://github.com/kroxchan/xinyi/discussions) 先聊一聊，避免重复造轮子

---

## 如何参与

| 方式 | 说明 |
|------|------|
| 🐛 报告 Bug | 提 [Issue](https://github.com/kroxchan/xinyi/issues) |
| 💡 提出想法 | 去 [Discussions](https://github.com/kroxchan/xinyi/discussions) |
| 🔧 写代码 | Fork → PR（参考上方检查清单） |
| 📖 改进文档 | 直接提 PR 修改 `docs/` 或 `README.md` |
| ⭐ Star 支持 | 给项目点 Star，让更多人看到 |
