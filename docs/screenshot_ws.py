"""
尝试通过 Gradio WebSocket 协议连接应用并截图。
"""
import asyncio
import json
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:7872"


async def get_ws_url() -> str:
    """从 /info 接口获取 WebSocket URL。"""
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{BASE_URL}/info")
        if resp.status_code != 200:
            return ""
        data = resp.json()
        return data.get("websocket_url", "")


async def main():
    # 获取 websocket URL
    ws_url = await get_ws_url()
    print(f"WebSocket URL: {ws_url}")

    # 尝试通过 WS 连接
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 监听 WebSocket 连接
        async with page.expect_websocket() as ws_info:
            print(f"导航到 {BASE_URL} …")
            try:
                await page.goto(BASE_URL, wait_until="commit", timeout=10000)
            except Exception as e:
                print(f"goto: {e}")

        ws = ws_info.value
        print(f"WebSocket 已连接: {ws.url}")

        # 等待页面渲染
        await asyncio.sleep(5)

        # 截图
        out_path = Path(__file__).parent / "images" / "ws-test.png"
        out_path.parent.mkdir(exist_ok=True)
        await page.screenshot(path=str(out_path), full_page=False)
        sz = out_path.stat().st_size // 1024
        print(f"截图: {out_path.name} ({sz}KB)")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
