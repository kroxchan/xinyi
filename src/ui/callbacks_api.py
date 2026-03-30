"""API configuration callbacks extracted from app.py.

These are called during build_ui() to read/write the API configuration
and render status HTML used by the setup tab.
"""
from __future__ import annotations

import logging
import yaml
from pathlib import Path

from src.ui.ux_helpers import UXHelper

logger = logging.getLogger(__name__)

# Paths — resolved relative to app.py source file
_APP_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = _APP_DIR / "config.yaml"


def load_config():
    import os as _os
    """Load config.yaml with ${VAR:default} env-var substitution."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    def _resolve(val):
        if isinstance(val, str):
            import re as _re
            for m in reversed(list(_re.finditer(r'\$\{([^}:]+)(?::([^}]*))?\}', val))):
                val = val.replace(m.group(0), _os.environ.get(m.group(1), m.group(2) or ""))
            return val
        if isinstance(val, dict):
            return {k: _resolve(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_resolve(v) for v in val]
        return val

    return _resolve(raw)


# ---------------------------------------------------------------------------
# API field helpers
# ---------------------------------------------------------------------------

def load_api_fields() -> tuple[str, str, str, str]:
    """Return (api_key, base_url, model, provider) from resolved config."""
    try:
        resolved = load_config()
        api = resolved.get("api", {})
        with open(CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        api_raw = raw.get("api", {})
        return (
            api.get("api_key", "") or api_raw.get("api_key", ""),
            str(api.get("base_url") or api_raw.get("base_url") or ""),
            api.get("model", "") or api_raw.get("model", ""),
            api.get("provider", "openai") or api_raw.get("provider", "openai"),
        )
    except Exception:
        return "", "", "", "openai"


# ---------------------------------------------------------------------------
# Re-init helpers (called after saving new config)
# ---------------------------------------------------------------------------

def _do_reinit():
    """Re-initialise app components after config save. Returns (error_str or None)."""
    from src.logging_config import get_logger
    _log = get_logger(__name__)

    try:
        import src.app as _app_module
        _cfg = load_config()
        new_components = _app_module.init_components(_cfg)
        # 必须直接写回 app 模块的全局变量，否则运行时仍用旧配置
        _app_module.components = new_components
        _app_module.init_error = None
        from src.engine.advisor_registry import get_registry as _gr
        _gr().reload()
        from src.engine.session import SessionManager
        _app_module.session_mgr = SessionManager(directory="data/sessions")
        from src.engine.persona import PersonaManager
        _app_module.persona_mgr = PersonaManager(directory="data/personas")
        from src.data.contact_registry import ContactRegistry
        _app_module.contact_registry = ContactRegistry()
        _app_module.ensure_couple_personas()
        import threading
        threading.Thread(target=new_components["embedder"].warmup, daemon=True).start()
        _log.info("API 配置保存后重新初始化成功")
        return None
    except Exception as e:
        import src.app as _app_module
        _app_module.init_error = str(e)
        _log.error("API 保存后重新初始化失败: %s", e)
        return UXHelper.format_error(
            title="初始化失败",
            message=f"组件加载出错：{str(e)[:100]}",
            solution="1. 检查 API Key 是否正确\n2. 检查网络连接\n3. 确认 API 服务可用\n4. 查看终端日志了解详情",
        )


# ---------------------------------------------------------------------------
# API save callbacks
# ---------------------------------------------------------------------------

def save_api(provider: str, model: str, key: str, base_url: str) -> str:
    """Save API config to config.yaml and reinitialise components."""
    if not (key or "").strip():
        return UXHelper.format_error(
            title="配置不完整",
            message="API Key 不能为空",
            solution="请前往 OpenAI / Anthropic 官网获取 API Key",
        )
    try:
        cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8")) or {}
    except Exception:
        cfg = {}
    if "api" not in cfg:
        cfg["api"] = {}
    cfg["api"]["provider"] = (provider or "openai").strip()
    model_stripped = (model or "").strip()
    cfg["api"]["model"] = model_stripped
    cfg["api"]["extraction_model"] = model_stripped
    cfg["api"]["api_key"] = (key or "").strip()
    cfg["api"]["base_url"] = (base_url or "").strip() or None
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

    error = _do_reinit()
    if error is None:
        return UXHelper.format_success("已保存并初始化完成，可以开始使用。")
    return (
        UXHelper.format_success("已保存。")
        + UXHelper.format_warning(
            title="初始化失败",
            message=f"保存成功但初始化出错（{error[:80]}），请检查配置后刷新页面。",
            hint="可在「设置」Tab 重新保存，或查看终端日志了解详情。",
        )
    )


def save_api_and_refresh(provider: str, model: str, key: str, base_url: str) -> tuple[str, str]:
    """Same as save_api but also returns current system info."""
    from src.app import get_system_info
    msg = save_api(provider, model, key, base_url)
    try:
        status = get_system_info()
    except Exception:
        status = "（系统状态暂时无法读取，请点击「刷新」）"
    return msg, status


# ---------------------------------------------------------------------------
# Pipeline status helpers (used by setup tab)
# ---------------------------------------------------------------------------

def step_done_html(label: str, done: bool, detail: str = "") -> str:
    """Render a step done indicator. Re-exported from shared for convenience."""
    from src.ui.shared import _step_done_html
    return _step_done_html(label, done, detail)


def setup1_status_html() -> str:
    """Render the "连接" tab status overview."""
    from src.ui.shared import _step_done_html
    from src.app import _detect_pipeline_status
    st = _detect_pipeline_status()
    from src.ui.callbacks_api import load_api_fields
    ak2, bu2, md2, pv2 = load_api_fields()
    has_api2 = bool(ak2)
    hd = st.get("has_decrypted", False)
    return (
        step_done_html("API 已配置", has_api2, pv2 + " / " + md2 if has_api2 else "未配置") + "<br>"
        + step_done_html("解密工具", st["has_scanner"], "已编译" if st["has_scanner"] else "") + "<br>"
        + step_done_html("密钥提取", st["has_keys"],
                         "{} 个密钥".format(st.get("key_count", 0)) if st["has_keys"] else "") + "<br>"
        + step_done_html("数据库解密", hd,
                         "{} 个数据库".format(st.get("db_count", 0)) if hd else "")
    )


def step3_decrypt_banner_html() -> str:
    """Render the Step 3 decrypt banner."""
    from src.ui.shared import _step3_decrypt_banner_html
    return _step3_decrypt_banner_html()


# ---------------------------------------------------------------------------
# Pipeline step functions — delegates to app.py originals
# (kept here so tab_setup.py and app.py build_ui() share the same calls)
# ---------------------------------------------------------------------------

def run_step1_prepare():
    from src.app import run_step1_prepare as _fn
    return _fn()


def run_step2_check_keys():
    from src.app import run_step2_check_keys as _fn
    return _fn()


def run_step2_reextract_instructions():
    from src.app import run_step2_reextract_instructions as _fn
    return _fn()


def run_step3_decrypt_only():
    from src.app import run_step3_decrypt_only as _fn
    return _fn()


def link_external_dir(path_str: str) -> tuple[str, str]:
    from src.app import link_external_dir as _link_ext
    return _link_ext(path_str)


# ---------------------------------------------------------------------------
# Guide HTML constants (copied from app.py lines 1229-1320)
# ---------------------------------------------------------------------------

STEP1_GUIDE_HTML = """
<div style="background:var(--block-background-fill,#f7f7f8);border-radius:10px;padding:20px;margin:8px 0">
<div style="font-weight:600;font-size:1.1em;margin-bottom:12px">准备读取聊天记录</div>
<p style="margin:0 0 8px">自动准备解密工具，让心译能读懂你的微信聊天数据。</p>
</div>
"""


def _build_step2_guide_html(repo_dir: str) -> str:
    import platform as _plat
    _sys = _plat.system()

    _card = (
        "<div style='background:var(--block-background-fill,#f7f7f8);"
        "border-radius:10px;padding:20px;margin:8px 0'>"
    )
    _code = (
        "<div style='background:#1e1e2e;color:#cdd6f4;border-radius:8px;"
        "padding:14px 16px;font-family:monospace;font-size:.9em;margin:10px 0;user-select:all'>"
    )
    _hint = "<p style='margin:8px 0 0;font-size:.85em;opacity:.7'>"

    if _sys == "Windows":
        return (
            f"{_card}"
            "<div style='font-weight:600;font-size:1.1em;margin-bottom:12px'>获取访问权限</div>"
            "<p style='margin:0 0 10px'>读取微信进程内存需要管理员权限。<br>"
            "心译本身就是从终端启动的，<b>只需用管理员终端启动心译</b>，密钥提取会自动完成，不需要另开窗口。</p>"
            "<div style='background:#2a2225;border-radius:8px;padding:14px 16px;margin:0 0 12px'>"
            "<div style='font-size:.85em;color:#a8969a;margin-bottom:8px;font-weight:600'>如何以管理员方式启动心译</div>"
            "<ol style='margin:0;padding-left:18px;line-height:2;color:#d4c4c8;font-size:.9em'>"
            "<li>按 <kbd style='background:#3a3035;padding:1px 6px;border-radius:4px'>Win+X</kbd>，选「Windows PowerShell（管理员）」或「终端（管理员）」</li>"
            "<li>在管理员终端里切到项目目录，运行 <code>python src/app.py</code></li>"
            "<li>确保微信已打开并登录</li>"
            "<li>回到这里，点下方「提取密钥」按钮</li>"
            "</ol>"
            "</div>"
            f"{_hint}标题栏显示「管理员」说明权限正确；点「提取密钥」后稍等片刻，看到绿色提示即成功。</p>"
            "<details style='margin-top:12px;font-size:.85em'>"
            "<summary style='cursor:pointer;opacity:.7'>⚠️ 如果提示 Access Denied 或找不到进程</summary>"
            "<ul style='margin:4px 0 0;padding-left:20px;opacity:.8;line-height:1.8'>"
            "<li>确认 PowerShell 标题栏有「管理员」字样</li>"
            "<li>微信（Weixin.exe）正在运行且已登录</li>"
            "<li>若杀毒软件拦截了 Python，临时关闭或加白名单</li>"
            "</ul>"
            "</details>"
            "</div>"
        )
    elif _sys == "Linux":
        return (
            f"{_card}"
            "<div style='font-weight:600;font-size:1.1em;margin-bottom:12px'>获取访问权限</div>"
            "<p style='margin:0 0 8px'>Linux 需要 root 权限或 <code>CAP_SYS_PTRACE</code> 来读取微信进程内存。</p>"
            f"{_code}cd {repo_dir} && sudo python3 find_all_keys.py</div>"
            f"{_hint}看到 <code>Saved to all_keys.json</code> 就说明成功了，回来点下面的「检测密钥」按钮。</p>"
            "<details style='margin-top:12px;font-size:.85em'>"
            "<summary style='cursor:pointer;opacity:.7'>⚠️ 如果提示 Permission denied</summary>"
            "<p style='margin:8px 0 4px'>可以改用 ptrace capability 而不必全程 sudo：</p>"
            "<div style='background:#1e1e2e;color:#cdd6f4;border-radius:6px;padding:10px 14px;"
            "font-family:monospace;font-size:.85em;margin:4px 0'>"
            "sudo setcap cap_sys_ptrace+eip $(which python3)</div>"
            "</details>"
            "</div>"
        )
    else:  # macOS
        return (
            f"{_card}"
            "<div style='font-weight:600;font-size:1.1em;margin-bottom:12px'>获取访问权限</div>"
            "<p style='margin:0 0 8px'>macOS 安全机制限制，需要你在<b>终端</b>里手动运行一行命令来获取聊天数据的访问权限。</p>"
            f"{_code}cd {repo_dir} && sudo ./find_all_keys_macos</div>"
            f"{_hint}打开「终端」App → 粘贴上面的命令 → 输入电脑密码 → 等待扫描完成。<br>"
            "看到 <code>Saved to all_keys.json</code> 就说明成功了，回来点下面的「检测密钥」按钮。</p>"
            "<details style='margin-top:12px;font-size:.85em'>"
            "<summary style='cursor:pointer;opacity:.7'>⚠️ 如果提示 task_for_pid failed（首次需要）</summary>"
            "<p style='margin:8px 0 4px'>需要临时关闭 SIP 调试限制（一次性操作）：</p>"
            "<ol style='margin:0;padding-left:20px;opacity:.8'>"
            "<li>关机 → 按住电源键直到看到「选项」→ 点「选项」进入恢复模式</li>"
            "<li>顶部菜单「实用工具」→「终端」，输入：<code>csrutil enable --without debug</code></li>"
            "<li>重启回来，重新运行上面的命令</li>"
            "<li>用完后可以恢复：再次进恢复模式输入 <code>csrutil enable</code></li>"
            "</ol>"
            "</details>"
            "</div>"
        )


STEP3_GUIDE_HTML = """
<div style="background:var(--block-background-fill,#f7f7f8);border-radius:10px;padding:20px;margin:8px 0">
<div style="font-weight:600;font-size:1.1em;margin-bottom:12px">开始学习 TA 的说话方式</div>
<p style="margin:0">请先选择对象。准备就绪后，点击下方按钮：读取聊天记录 → 学习 TA 的语气 → 构建记忆</p>
</div>
"""
