#!/usr/bin/env python3
"""Extract tabs and shared UI helpers from app.py into separate module files."""

import re
from pathlib import Path

SRC = Path("src/app.py")
OUT_UI = Path("src/ui")
OUT_TABS = OUT_UI / "tabs"

# ==============================================================================
# SHARED HELPERS - used across multiple tabs
# ==============================================================================
SHARED_HELPERS = [
    # (name, start_line, end_line)
    ("_stat_card", 875, 883),
    ("_step_html", 884, 898),
    ("_wordcloud_html", 899, 917),
    ("_persona_dropdown_choices", 918, 930),
    ("_persona_header_html", 931, 950),
    ("_build_hbar_chart_html", 2447, 2470),
    ("_build_vbar_chart_html", 2471, 2496),
    ("_build_relationship_html", 2497, 2511),
    ("_build_belief_summary_html", 2512, 2552),
    ("_build_persona_html", 2553, 2624),  # approximate end
]

# ==============================================================================
# TAB BLOCKS - full with gr.Tab() blocks
# ==============================================================================
TAB_BLOCKS = [
    # (tab_name, tab_id, start_line, end_line)
    ("连接", "tab-setup-1", 2964, 3112),
    ("选择 TA", "tab-setup-2", 3113, 3222),
    ("心译对话", "tab-chat", 3223, 3497),
    ("关系报告", "tab-eval", 3498, 4128),
    ("校准", "tab-cognitive", 4129, 4357),
    ("数据洞察", "tab-analytics", 4358, 4385),
    ("内心地图", "tab-beliefs", 4386, 4404),
    ("记忆", "tab-memories", 4405, 4457),
    ("设置", "tab-system", 4458, 4533),
]


def read_file(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def write_file(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_range(lines: list[str], start: int, end: int) -> list[str]:
    """Extract lines (1-indexed) as list of strings."""
    return lines[start - 1 : end]


def main():
    content = SRC.read_text(encoding="utf-8")
    lines = content.split("\n")
    total_lines = len(lines)
    print(f"Read {total_lines} lines from {SRC}")

    # Create directories
    OUT_UI.mkdir(parents=True, exist_ok=True)
    OUT_TABS.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # 1. Create shared.py with shared UI helpers
    # --------------------------------------------------------------------------
    print("\n=== Creating shared.py ===")
    shared_lines = [
        '"""Shared UI helpers — extracted from app.py"""',
        "from __future__ import annotations",
        "",
        "import gradio as gr",
        "from pathlib import Path",
        "import yaml",
        "",
        "# Global state accessed via parameters (passed from app.py)",
        "",
        "",
    ]

    # Add each shared helper
    for name, start, end in SHARED_HELPERS:
        helper_lines = extract_range(lines, start, end)
        shared_lines.extend(helper_lines)
        shared_lines.append("")
        print(f"  Added {name} (lines {start}-{end})")

    write_file(OUT_UI / "shared.py", shared_lines)
    print(f"  Wrote {OUT_UI / 'shared.py'}")

    # --------------------------------------------------------------------------
    # 2. Create each Tab file
    # --------------------------------------------------------------------------
    for tab_name, tab_id, start, end in TAB_BLOCKS:
        print(f"\n=== Creating tab for '{tab_name}' (lines {start}-{end}) ===")
        
        tab_lines = extract_range(lines, start, end)
        
        # Create the tab file
        safe_name = tab_name.lower().replace(" ", "_").replace("TA", "ta")
        tab_file = OUT_TABS / f"tab_{safe_name}.py"
        
        content_lines = [
            f'"""Tab: {tab_name} — extracted from app.py"""',
            "from __future__ import annotations",
            "",
            "import gradio as gr",
            "",
            "",
        ]
        
        # Add the Tab block
        content_lines.extend(tab_lines)
        
        write_file(tab_file, content_lines)
        print(f"  Wrote {tab_file}")

    # --------------------------------------------------------------------------
    # 3. Create __init__.py for tabs package
    # --------------------------------------------------------------------------
    init_lines = [
        '"""UI Tabs package — extracted from app.py"""',
        "from __future__ import annotations",
        "",
    ]
    for tab_name, _, _, _ in TAB_BLOCKS:
        safe_name = tab_name.lower().replace(" ", "_").replace("TA", "ta")
        init_lines.append(f"from .tab_{safe_name} import *")
    
    write_file(OUT_TABS / "__init__.py", init_lines)
    print(f"\n=== Created {OUT_TABS / '__init__.py'} ===")

    # --------------------------------------------------------------------------
    # 4. Create __init__.py for ui package
    # --------------------------------------------------------------------------
    ui_init_lines = [
        '"""UI package — extracted from app.py"""',
        "from __future__ import annotations",
        "",
        "from . import shared",
        "from . import tabs",
        "",
    ]
    write_file(OUT_UI / "__init__.py", ui_init_lines)
    print(f"=== Created {OUT_UI / '__init__.py'} ===")

    print("\n=== Extraction complete! ===")
    print("\nNext steps:")
    print("1. Review and fix imports in each tab_*.py file")
    print("2. Update shared.py with proper global variable access pattern")
    print("3. Rewrite app.py build_ui() to import and call each tab renderer")


if __name__ == "__main__":
    main()
