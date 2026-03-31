"""
用 Playwright 连接 xinyi 应用截图，使用 /info 接口探测是否就绪。
"""
import asyncio
import re
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(exist_ok=True)
BASE_URL = "http://localhost:7872"


TABS = [
    ("tab-setup-1",   "01-connect.png"),
    ("tab-chat",      "02-xinyi-chat.png"),
    ("tab-eval",      "03-relationship-report.png"),
    ("tab-cognitive", "04-calibration.png"),
    ("tab-analytics", "05-data-insights.png"),
    ("tab-beliefs",   "06-inner-map.png"),
    ("tab-memories",  "07-memory-bank.png"),
    ("tab-system",    "08-settings.png"),
]


async def is_app_ready(url: str) -> bool:
    """通过 /info 接口探测应用是否就绪。"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/info")
            return resp.status_code == 200
    except Exception:
        return False


async def main():
    print(f"探测应用状态: {BASE_URL}")
    ready = await is_app_ready(BASE_URL)
    print(f"应用就绪: {ready}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 隐藏顶栏
        await page.add_init_script("""
        () => {
            const s = document.createElement('style');
            s.textContent = `
                header, .gradio-header, .top-bar, .gradio-top-bar,
                gradio-app > header, .gradio-container > header,
                .gradio-header { display: none !important; }
            `;
            document.head.appendChild(s);
        }
        """)

        print(f"访问 {BASE_URL} (commit) …")
        try:
            # 用 commit 等待：HTML 收到就停，不等所有资源
            resp = await page.goto(BASE_URL, wait_until="commit", timeout=15000)
            print(f"  HTTP {resp.status if resp else 'N/A'}")
        except Exception as e:
            print(f"  goto 异常: {e}")

        # 等 JS 执行，轮询 shadow DOM 直到出现 tab button
        print("等待 Gradio 渲染 …")
        for i in range(20):
            await asyncio.sleep(1)
            # 检查 shadow DOM
            found = await page.evaluate("""
            () => {
                function search(root, depth) {
                    if (!root || depth > 6) return null;
                    let sr = null;
                    try { sr = root.shadowRoot; } catch(e) {}
                    if (sr) {
                        const btns = sr.querySelectorAll ? sr.querySelectorAll('button[id*="tab"]') : [];
                        if (btns.length > 0) return Array.from(btns).map(b => b.id);
                    }
                    const kids = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                    for (const k of kids) {
                        try {
                            if (k.shadowRoot) {
                                const r = search(k.shadowRoot, depth+1);
                                if (r) return r;
                            }
                        } catch(e) {}
                    }
                    return null;
                }
                return search(document, 0);
            }
            """)
            if found:
                print(f"  Gradio 就绪（{i+1}s）: {found}")
                break
            if i == 9:
                print(f"  {i+1}s: 仍无 tab button，当前 URL: {page.url}")

        # 截图
        for tab_id, filename in TABS:
            out_path = OUT_DIR / filename
            if out_path.exists():
                print(f"[skip] {filename}")
                continue

            print(f"\n→ #{tab_id} …")
            # JS 点击
            clicked = await page.evaluate(f"""
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
                        try {{ if (k.shadowRoot && findAndClick(k.shadowRoot, depth+1)) return true; }} catch(e) {{}}
                    }}
                    return false;
                }}
                return findAndClick(document, 0);
            }}
            """, tab_id)
            print(f"  click={clicked}")
            await asyncio.sleep(2.5)
            await page.screenshot(path=str(out_path), full_page=False, animations="disabled")
            sz = out_path.stat().st_size // 1024
            print(f"  ✓ {filename} ({sz}KB)")

        await browser.close()

    print(f"\n完成: {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
