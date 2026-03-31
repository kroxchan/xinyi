"""
尝试通过 Chrome DevTools Protocol 连接用户正在使用的浏览器会话。
需要 Chrome 启动时加 --remote-debugging-port=9222（多数浏览器默认不加）。
"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # 方法1: 尝试连接 Chrome 调试端口
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            contexts = browser.contexts
            print(f"CDP connected! Contexts: {len(contexts)}")
            if contexts:
                page = contexts[0].pages[0]
                print(f"Page URL: {page.url}")
            await browser.close()
            return
        except Exception as e:
            print(f"CDP 失败: {e}")

        # 方法2: 尝试直接用 playwright 启动并导航
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto("http://localhost:7872", wait_until="domcontentloaded", timeout=15000)
            html = await page.evaluate("() => document.body ? document.body.innerHTML.slice(0,500) : 'NO BODY'")
            print(f"New browser HTML: {html}")
            await browser.close()
        except Exception as e:
            print(f"新浏览器失败: {e}")

asyncio.run(main())
