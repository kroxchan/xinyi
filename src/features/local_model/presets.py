"""本地模型一键预设管理 — LocalModelPresets"""
from __future__ import annotations

import requests
from typing import Optional


class LocalModelPresets:
    """本地模型一键预设管理。

    支持 Ollama、LM Studio、Cherry Studio、OneAPI/NewAPI 等本地模型平台。
    提供预设配置、健康检查和配置格式化功能。
    """

    PRESETS: dict[str, dict] = {
        "ollama": {
            "name": "Ollama（本地）",
            "provider": "openai",
            "base_url": "http://localhost:11434/v1",
            "models": [
                {"id": "qwen2.5:14b", "label": "Qwen 2.5 14B（推荐）", "description": "中文效果好，速度快"},
                {"id": "llama3.1:8b", "label": "Llama 3.1 8B", "description": "英文为主"},
                {"id": "deepseek-v2.5", "label": "DeepSeek V2.5", "description": "中英文皆可"},
                {"id": "phi3:14b", "label": "Phi-3 14B", "description": "微软模型，小而精"},
                {"id": "custom", "label": "自定义模型", "description": "手动输入模型名"},
            ],
            "check_url": "http://localhost:11434/api/tags",
        },
        "lmstudio": {
            "name": "LM Studio（本地）",
            "provider": "openai",
            "base_url": "http://localhost:1234/v1",
            "models": [
                {"id": "custom", "label": "自定义模型", "description": "手动输入模型名"},
            ],
            "check_url": "http://localhost:1234/v1/models",
        },
        "oneapi": {
            "name": "OneAPI / NewAPI（代理）",
            "provider": "openai",
            "base_url": "",
            "models": [
                {"id": "custom", "label": "自定义模型", "description": "手动输入模型名"},
            ],
            "check_url": None,
        },
        "cherrystudio": {
            "name": "Cherry Studio（本地）",
            "provider": "openai",
            "base_url": "http://localhost:8000/v1",
            "models": [
                {"id": "custom", "label": "自定义模型", "description": "手动输入模型名"},
            ],
            "check_url": "http://localhost:8000/v1/models",
        },
    }

    @staticmethod
    def check_connection(base_url: str, timeout: float = 5.0) -> tuple[bool, str]:
        """检查本地模型是否可用。返回 (是否成功, 状态消息)。"""
        if not base_url:
            return False, "Base URL 为空"

        try:
            if "/api/tags" in base_url:
                resp = requests.get(base_url, timeout=timeout)
            elif base_url.endswith("/v1"):
                resp = requests.get(base_url.replace("/v1", "/v1/models"), timeout=timeout)
            else:
                resp = requests.get(base_url + "/v1/models", timeout=timeout)

            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", []) if isinstance(data, dict) else data if isinstance(data, list) else []
                model_names = []
                if isinstance(models, list):
                    for m in models[:5]:
                        if isinstance(m, dict):
                            model_names.append(m.get("name", m.get("id", "unknown")))
                        elif isinstance(m, str):
                            model_names.append(m)
                if model_names:
                    return True, f"在线，可用模型：{', '.join(model_names)}"
                return True, "在线（未检测到模型，请确认已加载模型）"
            return False, f"状态码：{resp.status_code}"
        except requests.ConnectionError:
            return False, "无法连接。请确认服务已启动。"
        except requests.Timeout:
            return False, "连接超时。"
        except Exception as e:
            return False, f"检查失败：{e}"

    @staticmethod
    def get_preset(preset_id: str) -> Optional[dict]:
        """获取预设配置。"""
        return LocalModelPresets.PRESETS.get(preset_id)

    @staticmethod
    def get_preset_choices() -> list[tuple[str, str]]:
        """获取预设下拉选项列表。"""
        choices = [
            ("暂不使用（继续用云端API）", "none"),
        ]
        for preset_id, preset in LocalModelPresets.PRESETS.items():
            label = preset["name"]
            if preset_id == "ollama":
                label = "Ollama（推荐）"
            choices.append((label, preset_id))
        return choices

    @staticmethod
    def format_config(preset_id: str, model_id: str, base_url: str = "") -> dict:
        """生成 config.yaml 格式的配置 dict。

        Args:
            preset_id: 预设 ID（如 "ollama"）
            model_id: 模型 ID（如 "qwen2.5:14b" 或 "custom"）
            base_url: 自定义的 Base URL（可选）

        Returns:
            适用于更新 config.yaml 的配置字典
        """
        preset = LocalModelPresets.get_preset(preset_id)
        if not preset:
            raise ValueError(f"未知预设：{preset_id}")

        final_base = base_url or preset.get("base_url", "")

        return {
            "provider": preset["provider"],
            "base_url": final_base,
            "model": model_id if model_id != "custom" else "",
            "api_key": "local",
        }

    @staticmethod
    def get_model_choices(preset_id: str) -> list[tuple[str, str]]:
        """获取指定预设的模型选项。"""
        preset = LocalModelPresets.get_preset(preset_id)
        if not preset:
            return []
        return [(m["label"], m["id"]) for m in preset["models"]]

    @staticmethod
    def get_default_model(preset_id: str) -> str:
        """获取指定预设的默认模型 ID。"""
        preset = LocalModelPresets.get_preset(preset_id)
        if preset and preset["models"]:
            return preset["models"][0]["id"]
        return "custom"

    @staticmethod
    def get_default_base_url(preset_id: str) -> str:
        """获取指定预设的默认 Base URL。"""
        preset = LocalModelPresets.get_preset(preset_id)
        if preset:
            return preset.get("base_url", "")
        return ""
