"""WeChat database decryption integration via ylytdeng/wechat-decrypt."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _real_python() -> str:
    """Return path to a usable Python interpreter for running pip.

    In a PyInstaller macOS .app bundle sys.executable points to the
    bundle binary itself; invoking it recursively deadlocks.
    We detect bundle (sys._MEIPASS) and fall back to the macOS system Python
    via xcrun, which is guaranteed to exist on every macOS system.
    On a PyInstaller Windows .exe bundle sys.executable is the .exe itself,
    which also deadlocks; we search for the real python.exe alongside it.
    On non-bundle platforms, returns sys.executable unchanged.
    """
    import sys as _sys
    import pathlib as _pathlib

    # Detect PyInstaller bundle
    meipass = getattr(_sys, "_MEIPASS", None)

    if meipass:
        system = _sys.platform
        if system == "darwin":
            # macOS bundle: use xcrun python3 — guaranteed to exist
            import subprocess as _subprocess
            try:
                r = _subprocess.run(
                    ["xcrun", "python3", "-c", "import sys; print(sys.executable)"],
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0:
                    return r.stdout.strip()
            except Exception:
                pass
            return "/usr/bin/python3"

        if system == "win32":
            # Windows bundle: find real python.exe next to the .exe or in known paths
            import subprocess as _subprocess
            exe_dir = _pathlib.Path(_sys.executable).parent

            # 1. python.exe next to the bundle (common with some packagers)
            nearby = exe_dir / "python.exe"
            if nearby.exists():
                return str(nearby)

            # 2. python.exe in parent directories (venv layout)
            for _ in range(4):
                exe_dir = exe_dir.parent
                nearby = exe_dir / "python.exe"
                if nearby.exists():
                    return str(nearby)

            # 3. Search in common user-level Python install locations
            import os as _os
            local_app = _os.environ.get("LOCALAPPDATA", "")
            search_roots = []
            if local_app:
                search_roots.append(_pathlib.Path(local_app) / "Programs" / "Python")
            # Also try to find via `py -0` (Python Launcher for Windows)
            try:
                r = _subprocess.run(
                    ["py", "-0a"], capture_output=True, text=True, timeout=15,
                    creationflags=_subprocess.CREATE_NO_WINDOW if hasattr(_subprocess, "CREATE_NO_WINDOW") else 0,
                )
                if r.returncode == 0:
                    lines = r.stdout.strip().splitlines()
                    # Find the latest version (e.g. "-3.11" or "-3.11-64")
                    py_lines = [l.strip() for l in lines if l.strip().startswith("-3.")]
                    if py_lines:
                        latest = py_lines[0].split()[0].lstrip("-")
                        r2 = _subprocess.run(
                            ["py", f"-{latest}", "-c", "import sys; print(sys.executable)"],
                            capture_output=True, text=True, timeout=15,
                        )
                        if r2.returncode == 0:
                            return r2.stdout.strip()
            except Exception:
                pass

            # 4. Search in search_roots
            for root in search_roots:
                if not root.exists():
                    continue
                try:
                    for ver_dir in sorted(root.iterdir(), reverse=True):
                        if ver_dir.is_dir():
                            python_exe = ver_dir / "python.exe"
                            if python_exe.exists():
                                return str(python_exe)
                            # Also check Scripts subfolder
                            scripts = ver_dir / "Scripts" / "python.exe"
                            if scripts.exists():
                                return str(scripts)
                except Exception:
                    pass

            # Fallback: use py launcher with latest available Python
            try:
                r = _subprocess.run(
                    ["py", "-3", "-c", "import sys; print(sys.executable)"],
                    capture_output=True, text=True, timeout=15,
                )
                if r.returncode == 0:
                    return r.stdout.strip()
            except Exception:
                pass

            return str(_sys.executable)  # last resort, may not work in bundle

    return _sys.executable


def _sudo_run(cmd_str: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a shell command with admin privileges via macOS GUI password dialog."""
    if platform.system() == "Darwin":
        escaped = cmd_str.replace("\\", "\\\\").replace('"', '\\"')
        apple_script = (
            'do shell script "{}" with administrator privileges'
        ).format(escaped)
        return subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True, text=True, timeout=timeout,
        )
    return subprocess.run(
        ["sudo", "sh", "-c", cmd_str],
        capture_output=True, text=True, timeout=timeout,
    )

VENDOR_DIR = Path("vendor")
REPO_DIR = VENDOR_DIR / "wechat-decrypt"
REPO_URL = "https://github.com/ylytdeng/wechat-decrypt.git"


class DecryptStep:
    """Result of a single decryption pipeline step."""

    def __init__(self, name: str, ok: bool, message: str, detail: str = "") -> None:
        self.name = name
        self.ok = ok
        self.message = message
        self.detail = detail

    def __repr__(self) -> str:
        icon = "✓" if self.ok else "✗"
        return f"[{icon}] {self.name}: {self.message}"


WECHAT_APP = Path("/Applications/WeChat.app")


class WeChatDecryptor:
    """Orchestrates the wechat-decrypt tool pipeline."""

    def __init__(self, output_dir: str = "data/raw") -> None:
        self.output_dir = Path(output_dir)
        self.system = platform.system()

    # ------------------------------------------------------------------
    # Step 0: Check prerequisites (Xcode CLT, WeChat installed & running)
    # ------------------------------------------------------------------

    def check_prerequisites(self) -> DecryptStep:
        if self.system == "Windows":
            return self._check_prerequisites_windows()
        if self.system != "Darwin":
            return DecryptStep("环境检查", True, "Linux 系统，跳过 macOS 专属检查")

        # macOS checks
        issues = []
        try:
            r = subprocess.run(
                ["xcode-select", "-p"], capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                issues.append("未安装 Xcode Command Line Tools（运行 xcode-select --install）")
        except FileNotFoundError:
            issues.append("未找到 xcode-select 命令")

        if not WECHAT_APP.exists():
            issues.append("未找到 /Applications/WeChat.app")

        r = subprocess.run(["pgrep", "-x", "WeChat"], capture_output=True, timeout=5)
        if r.returncode != 0:
            issues.append("微信未在运行，请先打开微信并登录")

        if issues:
            return DecryptStep("环境检查", False, "；".join(issues))
        return DecryptStep("环境检查", True, "Xcode CLT ✓ | 微信已安装 ✓ | 微信运行中 ✓")

    def _check_prerequisites_windows(self) -> DecryptStep:
        issues = []
        hints = []

        # 检查是否以管理员身份运行
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = False
        if not is_admin:
            issues.append("未以管理员身份运行")
            hints.append("请右键点击「命令提示符」或「PowerShell」→ 以管理员身份运行，再重新启动本程序")

        # 检查微信是否在运行
        wechat_running = False
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            wechat_running = "Weixin.exe" in r.stdout
        except Exception:
            pass
        if not wechat_running:
            issues.append("微信（Weixin.exe）未在运行")
            hints.append("请先打开微信并登录，再点击解密")

        if issues:
            detail = "；".join(hints) if hints else ""
            return DecryptStep("环境检查", False, "；".join(issues), detail)
        return DecryptStep("环境检查", True, "管理员权限 ✓ | 微信运行中 ✓")

    # ------------------------------------------------------------------
    # Step 0.5: Ad-hoc sign WeChat (remove hardened runtime)
    # ------------------------------------------------------------------

    def adhoc_sign_wechat(self) -> DecryptStep:
        if self.system != "Darwin":
            return DecryptStep("Ad-hoc 签名", True, "非 macOS，跳过")

        if not WECHAT_APP.exists():
            return DecryptStep("Ad-hoc 签名", False, "未找到 WeChat.app")

        try:
            r = subprocess.run(
                ["codesign", "-dvv", str(WECHAT_APP)],
                capture_output=True, text=True, timeout=10,
            )
            sig_info = r.stderr + r.stdout
            already_adhoc = "Signature=adhoc" in sig_info
            if already_adhoc:
                return DecryptStep("Ad-hoc 签名", True, "微信已是 ad-hoc 签名，无需重签")
        except Exception:
            pass

        app = str(WECHAT_APP)
        tmp = "/tmp/_WeChat_adhoc_sign.app"
        cmd = (
            "rm -rf {tmp} && "
            "cp -R {app} {tmp} && "
            "xattr -cr {tmp} && "
            "codesign --force --deep --sign - {tmp} && "
            "rm -rf {app} && "
            "mv {tmp} {app}"
        ).format(app=app, tmp=tmp)
        try:
            r = _sudo_run(cmd, timeout=180)
            if r.returncode != 0:
                detail = (r.stderr or r.stdout)[-500:]
                return DecryptStep("Ad-hoc 签名", False, "签名失败", detail)
            return DecryptStep(
                "Ad-hoc 签名", True,
                "签名完成 — 若微信闪退请重新打开即可",
            )
        except FileNotFoundError:
            return DecryptStep("Ad-hoc 签名", False, "未找到 osascript/codesign")
        except subprocess.TimeoutExpired:
            return DecryptStep("Ad-hoc 签名", False, "签名超时或用户取消了密码对话框")

    # ------------------------------------------------------------------
    # Step 0.7: Restart WeChat so the new signature takes effect
    # ------------------------------------------------------------------

    def restart_wechat(self) -> DecryptStep:
        if self.system != "Darwin":
            return DecryptStep("重启微信", True, "非 macOS，跳过")

        import time as _time

        subprocess.run(["pkill", "-x", "WeChat"], capture_output=True, timeout=10)
        _time.sleep(3)

        subprocess.Popen(["open", "-a", "WeChat"])
        _time.sleep(8)

        r = subprocess.run(["pgrep", "-x", "WeChat"], capture_output=True, timeout=5)
        if r.returncode != 0:
            return DecryptStep("重启微信", False, "微信未能重新启动，请手动打开微信后重试")
        return DecryptStep("重启微信", True, "微信已用新签名重启")

    # ------------------------------------------------------------------
    # Step 0.8: Ensure running WeChat has ad-hoc signature
    # ------------------------------------------------------------------

    def ensure_wechat_adhoc_running(self) -> DecryptStep:
        """Check disk signature is ad-hoc and WeChat is running."""
        if self.system != "Darwin":
            return DecryptStep("验证签名", True, "非 macOS，跳过")

        r = subprocess.run(
            ["codesign", "-dvv", str(WECHAT_APP)],
            capture_output=True, text=True, timeout=10,
        )
        if "Signature=adhoc" not in (r.stderr + r.stdout):
            return DecryptStep("验证签名", False, "WeChat.app 不是 ad-hoc 签名，请先完成签名步骤")

        r = subprocess.run(["pgrep", "-x", "WeChat"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return DecryptStep(
                "验证签名", False,
                "微信未在运行 — 请打开微信并登录后，再点一次「一键启动」",
            )

        pid = r.stdout.strip().split("\n")[0]
        return DecryptStep("验证签名", True, "磁盘签名 ad-hoc ✓ | 微信运行中 PID {}".format(pid))

    # ------------------------------------------------------------------
    # Step 1: Clone repository
    # ------------------------------------------------------------------

    def clone_repo(self) -> DecryptStep:
        if REPO_DIR.exists() and ((REPO_DIR / "decrypt_db.py").exists() or (REPO_DIR / "main.py").exists()):
            return DecryptStep("克隆仓库", True, "wechat-decrypt 已存在，跳过克隆")

        VENDOR_DIR.mkdir(parents=True, exist_ok=True)

        if REPO_DIR.exists():
            shutil.rmtree(REPO_DIR)

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", REPO_URL, str(REPO_DIR)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return DecryptStep("克隆仓库", False, "git clone 失败", result.stderr)
            return DecryptStep("克隆仓库", True, "克隆完成")
        except FileNotFoundError:
            return DecryptStep("克隆仓库", False, "未找到 git 命令，请先安装 git")
        except subprocess.TimeoutExpired:
            return DecryptStep("克隆仓库", False, "克隆超时（120s），请检查网络")

    # ------------------------------------------------------------------
    # Step 2: Install dependencies
    # ------------------------------------------------------------------

    def install_deps(self) -> DecryptStep:
        req_file = REPO_DIR / "requirements.txt"
        if not req_file.exists():
            return DecryptStep("安装依赖", True, "无 requirements.txt，跳过")

        SKIP_PKGS = {"mcp"}
        CRITICAL_PKGS = {"pycryptodome"}

        with open(req_file, encoding="utf-8") as f:
            raw_lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        def _pkg_name(line: str) -> str:
            import re as _re
            return _re.split(r"[><=!\[;]", line)[0].strip().lower()

        IMPORT_NAME = {
            "pycryptodome": "Crypto",
            "zstandard": "zstandard",
            "pycryptodomex": "Cryptodome",
        }

        def _is_installed(line: str) -> bool:
            try:
                import re as _re
                from importlib.util import find_spec as _find_spec
                pname = _re.split(r"[><=!\[;]", line)[0].strip().lower()
                for pkg, imp in IMPORT_NAME.items():
                    if pname.startswith(pkg):
                        if _find_spec(imp) is not None:
                            return True
                return _find_spec(pname.replace("-", "_")) is not None
            except Exception:
                return False

        skipped_compat: list[str] = []
        already_ok: list[str] = []
        to_install: list[str] = []

        for line in raw_lines:
            pname = _pkg_name(line)
            if pname in SKIP_PKGS:
                skipped_compat.append(pname)
                continue
            if _is_installed(line):
                already_ok.append(pname)
            else:
                to_install.append(line)

        if not to_install:
            return DecryptStep(
                "安装依赖", True,
                "所有依赖已安装 ✓（" + ", ".join(already_ok) + "）",
                "已有: " + ", ".join(already_ok) if already_ok else "",
            )

        failed: list[str] = []
        newly_installed: list[str] = []
        last_error_msg: str = ""

        # Build fallback manual install command
        fallback_pkgs = " ".join(to_install)
        fallback_cmd_template = (
            '<code style="font-size:.85em">{py} -m pip install {pkgs}</code><br>'
            '国内镜像：<code style="font-size:.85em">{py} -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple {pkgs}</code>'
        )

        def _pip_install(args: list) -> bool:
            """Run pip install, return True on success. Catches all subprocess errors."""
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=180)
                return r.returncode == 0
            except FileNotFoundError:
                return False
            except subprocess.TimeoutExpired:
                return False
            except OSError:
                return False

        def _get_pip_cmd(python_path: str) -> list:
            return [python_path, "-m", "pip", "install", "--quiet"]

        # Try system python first, then fall back to sys.executable
        python_path = _real_python()
        mirrors = [None, "https://pypi.tuna.tsinghua.edu.cn/simple"]

        for pkg_line in list(to_install):
            pname = _pkg_name(pkg_line)
            installed = False
            for mirror in mirrors:
                cmd = _get_pip_cmd(python_path) + ([pkg_line] if len(to_install) == 1 else [pkg_line])
                if mirror:
                    cmd += ["-i", mirror]
                if _pip_install(cmd):
                    newly_installed.append(pname)
                    installed = True
                    break
                # If python_path was bad, retry with sys.executable
                if python_path != sys.executable:
                    alt_python = sys.executable
                    alt_cmd = _get_pip_cmd(alt_python) + ([pkg_line] if len(to_install) == 1 else [pkg_line])
                    if mirror:
                        alt_cmd += ["-i", mirror]
                    if _pip_install(alt_cmd):
                        newly_installed.append(pname)
                        python_path = alt_python
                        installed = True
                        break
            if not installed:
                failed.append(pname)

        # Build detail message
        detail_parts = []
        if newly_installed:
            detail_parts.append("已装: " + ", ".join(newly_installed))
        if already_ok:
            detail_parts.append("已有: " + ", ".join(already_ok))
        if skipped_compat:
            detail_parts.append("跳过(不兼容): " + ", ".join(skipped_compat))
        if failed:
            detail_parts.append("失败: " + ", ".join(failed))
        detail = " | ".join(detail_parts)

        critical_failed = CRITICAL_PKGS & set(failed)
        if critical_failed:
            fallback = fallback_cmd_template.format(
                py=python_path if python_path != sys.executable else sys.executable,
                pkgs=" ".join(failed),
            )
            return DecryptStep(
                "安装依赖", False,
                "关键包 {} 安装失败，请在终端手动运行以下命令：".format(", ".join(critical_failed)),
                fallback,
            )

        if newly_installed and not failed:
            return DecryptStep("安装依赖", True, "已安装 " + ", ".join(newly_installed) + "，依赖安装完成", detail)
        if not newly_installed and not failed and already_ok:
            return DecryptStep("安装依赖", True, "所有依赖已安装 ✓（" + ", ".join(already_ok) + "）", detail)
        # Some non-critical failed
        if failed:
            fallback = fallback_cmd_template.format(
                py=python_path if python_path != sys.executable else sys.executable,
                pkgs=" ".join(failed),
            )
            return DecryptStep(
                "安装依赖", True,
                "非关键包 " + ", ".join(failed) + " 安装失败，可手动安装后继续",
                fallback + "\n\n" + detail,
            )

        return DecryptStep("安装依赖", True, "依赖安装完成", detail)

    # ------------------------------------------------------------------
    # Step 3: Compile macOS scanner (macOS only)
    # ------------------------------------------------------------------

    def compile_macos_scanner(self) -> DecryptStep:
        if self.system != "Darwin":
            return DecryptStep("编译扫描器", True, "当前系统 {}，跳过 macOS 编译".format(self.system))

        scanner = REPO_DIR / "find_all_keys_macos"
        hook = REPO_DIR / "key_hook.dylib"

        if scanner.exists() and hook.exists():
            return DecryptStep("编译扫描器", True, "二进制已存在，跳过编译")

        source_scanner = REPO_DIR / "find_all_keys_macos.c"
        source_hook = REPO_DIR / "key_hook.c"

        try:
            if not scanner.exists() and source_scanner.exists():
                r = subprocess.run(
                    ["cc", "-O2", "-o", str(scanner), str(source_scanner), "-framework", "Foundation"],
                    capture_output=True, text=True, timeout=60,
                )
                if r.returncode != 0:
                    return DecryptStep("编译扫描器", False, "scanner 编译失败", r.stderr)

            if not hook.exists() and source_hook.exists():
                r = subprocess.run(
                    ["cc", "-shared", "-O2", "-o", str(hook), str(source_hook)],
                    capture_output=True, text=True, timeout=60,
                )
                if r.returncode != 0:
                    return DecryptStep("编译扫描器", False, "hook dylib 编译失败", r.stderr)

            return DecryptStep("编译扫描器", True, "编译完成（scanner + hook dylib）")
        except FileNotFoundError:
            return DecryptStep("编译扫描器", False, "未找到 cc 编译器，请运行: xcode-select --install")

    # ------------------------------------------------------------------
    # Step 4: Extract keys (requires sudo + WeChat running)
    # ------------------------------------------------------------------

    def _check_keys_file(self) -> int:
        """Return number of keys in all_keys.json, or 0 if empty/missing."""
        keys_file = REPO_DIR / "all_keys.json"
        if not keys_file.exists():
            return 0
        try:
            with open(keys_file) as f:
                keys = json.load(f)
            if isinstance(keys, list):
                return len(keys)
            if isinstance(keys, dict):
                return len([k for k in keys if k])
            return 0
        except (json.JSONDecodeError, ValueError):
            return 0

    def _extract_via_sudo(self) -> bool:
        """Try the standard sudo scanner. Returns True if keys were found."""
        binary = REPO_DIR / "find_all_keys_macos"
        if not binary.exists():
            return False
        try:
            _sudo_run(
                "cd {} && {}".format(str(REPO_DIR.resolve()), str(binary.resolve())),
                timeout=60,
            )
        except Exception:
            pass
        return self._check_keys_file() > 0

    def _extract_via_dylib(self) -> bool:
        """Inject dylib into WeChat to scan from inside (no SIP needed)."""
        import time as _time

        hook = REPO_DIR.resolve() / "key_hook.dylib"
        if not hook.exists():
            return False

        signal_file = Path("/tmp/wechat_keys_done")
        output_file = Path("/tmp/wechat_all_keys.json")
        for f in (signal_file, output_file):
            if f.exists():
                f.unlink()

        subprocess.run(["pkill", "-x", "WeChat"], capture_output=True, timeout=10)
        _time.sleep(3)

        logger.info("以 DYLD_INSERT_LIBRARIES 方式启动微信（提取密钥）…")
        wechat_bin = WECHAT_APP / "Contents" / "MacOS" / "WeChat"
        env = dict(subprocess.os.environ)
        env["DYLD_INSERT_LIBRARIES"] = str(hook)
        subprocess.Popen([str(wechat_bin)], env=env)

        for _ in range(18):
            _time.sleep(5)
            if signal_file.exists():
                break

        if not output_file.exists():
            return False

        keys_file = REPO_DIR / "all_keys.json"
        import shutil
        shutil.copy2(str(output_file), str(keys_file))
        return self._check_keys_file() > 0

    def extract_keys(self) -> DecryptStep:
        if self.system == "Darwin":
            if self._extract_via_sudo():
                count = self._check_keys_file()
                return DecryptStep("提取密钥", True, "（sudo 方式）提取到 {} 个密钥".format(count))

            logger.info("sudo 方式失败（SIP 限制），尝试 dylib 注入方式…")
            if self._extract_via_dylib():
                count = self._check_keys_file()
                return DecryptStep(
                    "提取密钥", True,
                    "（dylib 注入方式）提取到 {} 个密钥 — 请重新登录微信".format(count),
                )

            return DecryptStep(
                "提取密钥", False,
                "两种方式均失败，请检查微信是否 ad-hoc 签名并正在运行",
            )
        else:
            script = REPO_DIR / "find_all_keys.py"
            if not script.exists():
                return DecryptStep("提取密钥", False, "未找到 find_all_keys.py")
            try:
                # Use _real_python() so the subprocess actually runs a Python
                # interpreter (not the .app binary in a PyInstaller bundle).
                python_path = self._real_python()
                result = subprocess.run(
                    [python_path, str(script.resolve())],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(REPO_DIR.resolve()),
                )
                if result.returncode != 0:
                    return DecryptStep("提取密钥", False, "密钥提取失败", result.stderr)
                return DecryptStep("提取密钥", True, "提取完成", result.stdout[-500:])
            except subprocess.TimeoutExpired:
                return DecryptStep("提取密钥", False, "提取超时")

    # ------------------------------------------------------------------
    # Step 5: Decrypt databases
    # ------------------------------------------------------------------

    @staticmethod
    def _find_wechat_db_dir() -> str:
        """Auto-detect WeChat's db_storage directory on macOS."""
        import os
        home = os.path.expanduser("~")
        base = os.path.join(
            home,
            "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files",
        )
        if not os.path.isdir(base):
            return ""
        candidates = []
        for name in os.listdir(base):
            storage = os.path.join(base, name, "db_storage")
            if os.path.isdir(storage):
                candidates.append(storage)
        if not candidates:
            return ""
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]

    @staticmethod
    def _real_python() -> str:
        """Return path to a usable Python interpreter for running pip.

        In a PyInstaller macOS .app bundle sys.executable points to the
        bundle binary itself; invoking it recursively deadlocks.
        We detect bundle (sys._MEIPASS) and fall back to the macOS system Python
        via xcrun, which is guaranteed to exist on every macOS system.
        """
        import sys as _sys
        import pathlib as _pathlib

        meipass = getattr(_sys, "_MEIPASS", None)
        if meipass:
            system = _sys.platform
            if system == "darwin":
                import subprocess as _subprocess
                try:
                    r = _subprocess.run(
                        ["xcrun", "python3", "-c", "import sys; print(sys.executable)"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode == 0:
                        return r.stdout.strip()
                except Exception:
                    pass
                return "/usr/bin/python3"
            if system == "win32":
                import subprocess as _subprocess
                exe_dir = _pathlib.Path(_sys.executable).parent
                nearby = exe_dir / "python.exe"
                if nearby.exists():
                    return str(nearby)
                for _ in range(4):
                    exe_dir = exe_dir.parent
                    nearby = exe_dir / "python.exe"
                    if nearby.exists():
                        return str(nearby)
                return str(_sys.executable)
        return sys.executable

    def decrypt_databases(self) -> DecryptStep:
        # --- Fast-fail pre-check ---
        try:
            from Crypto.Cipher import AES as _aes
        except ImportError:
            return DecryptStep(
                "解密数据库", False,
                "缺少 pycryptodome，请回到第 1 步重新准备解密工具",
            )

        repo_abs = REPO_DIR.resolve()
        script = repo_abs / "decrypt_db.py"
        if not script.exists():
            return DecryptStep("解密数据库", False, "未找到 decrypt_db.py")

        config_file = repo_abs / "config.json"
        cfg = {}
        if config_file.exists():
            with open(config_file) as f:
                cfg = json.load(f)

        db_dir = self._find_wechat_db_dir()
        if db_dir:
            cfg["db_dir"] = db_dir
            logger.info("检测到微信数据目录: %s", db_dir)

        cfg["decrypted_dir"] = str(self.output_dir.resolve())
        with open(config_file, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        import subprocess as _subprocess

        try:
            # Use _real_python() instead of sys.executable so the subprocess
            # actually runs a Python interpreter (not the .app binary in a bundle).
            python_path = self._real_python()
            proc = _subprocess.Popen(
                [python_path, str(script)],
                stdout=_subprocess.PIPE,
                stderr=_subprocess.PIPE,
                text=True,
                cwd=str(repo_abs),
            )
            stdout, stderr = proc.communicate()
            step = DecryptStep("解密数据库", False, "")   # temp; will overwrite
            step._subprocess_pid = proc.pid
            step._stdout = stdout

            if proc.returncode != 0:
                if "Crypto" in stderr or "pycryptodome" in stderr:
                    step.ok = False
                    step.message = "pycryptodome 缺失，请回到第 1 步重新准备解密工具"
                    step.detail = stderr[-500:]
                else:
                    step.ok = False
                    step.message = "解密失败"
                    step.detail = stderr[-500:]
            else:
                db_count = len(list(self.output_dir.rglob("*.db")))
                step.ok = True
                step.message = "解密完成，{} 个数据库文件".format(db_count)

            return step
        except Exception as e:
            return DecryptStep("解密数据库", False, "解密异常：" + str(e))

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def run_full_pipeline(self):
        """Generator that yields DecryptStep for each stage."""
        step = self.check_prerequisites()
        yield step
        if not step.ok:
            return

        step = self.adhoc_sign_wechat()
        yield step
        if not step.ok:
            return

        step = self.clone_repo()
        yield step
        if not step.ok:
            return

        step = self.install_deps()
        yield step
        if not step.ok:
            return

        step = self.compile_macos_scanner()
        yield step
        if not step.ok:
            return

        step = self.ensure_wechat_adhoc_running()
        yield step
        if not step.ok:
            return

        step = self.extract_keys()
        yield step
        if not step.ok:
            return

        yield self.decrypt_databases()

    # ------------------------------------------------------------------
    # Link external decrypted directory
    # ------------------------------------------------------------------

    @staticmethod
    def link_decrypted_dir(source_path: str, target_dir: str = "data/raw") -> DecryptStep:
        """Copy/link an externally decrypted directory into our data/raw/."""
        src = Path(source_path).expanduser().resolve()
        tgt = Path(target_dir)

        if not src.exists():
            return DecryptStep("链接数据", False, f"路径不存在: {src}")

        if not src.is_dir():
            return DecryptStep("链接数据", False, f"路径不是目录: {src}")

        db_files = list(src.rglob("*.db"))
        if not db_files:
            return DecryptStep("链接数据", False, "目录中未找到 .db 文件")

        tgt.mkdir(parents=True, exist_ok=True)

        copied = 0
        for db_file in db_files:
            rel = db_file.relative_to(src)
            dest = tgt / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(db_file, dest)
                copied += 1

        existing = len(db_files) - copied
        msg = f"导入 {copied} 个数据库文件"
        if existing:
            msg += f"（{existing} 个已存在，跳过）"

        return DecryptStep("链接数据", True, msg)

    # ------------------------------------------------------------------
    # Scan directory info
    # ------------------------------------------------------------------

    @staticmethod
    def scan_directory(path: str) -> dict:
        """Scan a directory and return summary info about its contents."""
        p = Path(path).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            return {"valid": False, "error": "路径不存在或不是目录"}

        db_files = list(p.rglob("*.db"))
        has_contact = any("contact" in f.name for f in db_files)
        has_message = any("message" in f.name for f in db_files)

        return {
            "valid": True,
            "path": str(p),
            "db_count": len(db_files),
            "has_contact_db": has_contact,
            "has_message_db": has_message,
            "db_files": [str(f.relative_to(p)) for f in db_files[:30]],
        }
