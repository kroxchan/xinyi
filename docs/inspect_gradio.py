"""
通过 Gradio /config + Playwright 截各 Tab 页面。
"""
import asyncio
import json
import re
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(exist_ok=True)
BASE_URL = "http://localhost:7872"


def extract_tabs(config: dict) -> list[dict]:
    """从 Gradio config 提取 tabitem 组件。"""
    tabs = []
    for comp in config.get("components", []):
        if comp.get("type") == "tabitem":
            props = comp.get("props", {})
            tabs.append({
                "id":    props.get("id", ""),
                "label": props.get("label", ""),
                "comp_id": comp.get("id"),
            })
    return tabs


async def main():
    # ── 1. 获取 config ──────────────────────────────────────
    print("获取 Gradio config …")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/config")
        resp.raise_for_status()
        config = resp.json()

    tabs = extract_tabs(config)
    print(f"\n从 config 提取到的 Tab（{len(tabs)} 个）：")
    for t in tabs:
        print(f"  [{t['comp_id']}] #{t['id']}  label={t['label']!r}")

    # ── 2. Playwright 截图 ──────────────────────────────────
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 注入 CSS 隐藏 Gradio 顶栏
        await page.add_init_script("""
        () => {
            const s = document.createElement('style');
            s.textContent = `
                header, .gradio-header, .top-bar, #header,
                gradio-app > header, gradio-app > .top-bar,
                .gradio-container > header, .gradio-container > .top-bar,
                .gradio-header { display: none !important; }
                /* 去掉顶栏后再截 */
                gradio-app > div:first-child { padding-top: 0 !important; }
            `;
            document.head.appendChild(s);
        }
        """)

        print(f"\n访问 {BASE_URL} …")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # 诊断：打印 shadow-DOM 中的 tab button
        shadow_buttons = await page.evaluate("""
        () => {
            const results = [];
            function search(root, depth) {
                if (!root || depth > 8) return;
                const sel = '[id*="tab"], [id*="setup"], [id*="system"], [id*="chat"], [id*="eval"]';
                try {
                    root.querySelectorAll(sel).forEach(el => {
                        const bid = el.getAttribute('id') || '';
                        const txt = (el.innerText || '').replace(/\\n/g, ' ').trim().slice(0, 50);
                        const vis = el.offsetParent !== null;
                        results.push({bid, txt, vis});
                    });
                } catch(e) {}
                let sr = null;
                try { sr = root.shadowRoot; } catch(e) {}
                if (sr) search(sr, depth + 1);
                const kids = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                for (const kid of kids) {
                    try { if (kid.shadowRoot) search(kid.shadowRoot, depth + 1); } catch(e) {}
                }
            }
            search(document, 0);
            return results;
        }
        """)
        print(f"\nShadow DOM elements: {len(shadow_buttons)}")
        for b in shadow_buttons[:20]:
            print(f"  [{'v' if b['vis'] else 'h'}] #{b['bid']}: {b['txt']!r}")

        # ── 3. 逐 Tab 截图 ──────────────────────────────────
        for tab in tabs:
            tab_id  = tab["id"]
            label  = tab["label"]
            safe_label = re.sub(r'[\\/:*?"<>|]', '_', label)
            out_path = OUT_DIR / f"01-{safe_label}.png"

            if out_path.exists():
                print(f"\n[skip] {out_path.name}")
                continue

            print(f"\n→ #{tab_id} ({label}) …")

            # JS 点击（穿透 shadow DOM）
            click_result = await page.evaluate(f"""
            (id) => {{
                function findAndClick(root, depth) {{
                    if (!root || depth > 8) return false;
                    let el = null;
                    try {{ el = root.querySelector('#' + id); }} catch(e) {{}}
                    if (el) {{ el.click(); return true; }}
                    let sr = null;
                    try {{ sr = root.shadowRoot; }} catch(e) {{}}
                    if (sr && findAndClick(sr, depth+1)) return true;
                    const kids = Array.from(root.querySelectorAll ? root.querySelectorAll('*') : []);
                    for (const k of kids) {{
                        try {{
                            if (k.shadowRoot && findAndClick(k.shadowRoot, depth+1)) return true;
                        }} catch(e) {{}}
                    }}
                    return false;
                }}
                return findAndClick(document, 0) ? 'CLICKED' : 'NOT_FOUND';
            }}
            """, tab_id)
            print(f"  click: {click_result}")
            await asyncio.sleep(2.5)

            # 截图（只截视口，不含浏览器地址栏/标签栏）
            await page.screenshot(
                path=str(out_path),
                full_page=False,
                animations="disabled",
            )
            sz = out_path.stat().st_size // 1024
            print(f"  ✓ {out_path.name}  ({sz}KB)")

        await browser.close()

    print(f"\n完成！截图保存在: {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
