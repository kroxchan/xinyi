"""xinyi — launcher for `python -m src` or `briefcase`."""
from src.app import build_ui, load_config

def main():
    load_config()
    app = build_ui()
    app.queue()
    # 双击 .app / .exe 自动打开浏览器访问 dashboard
    app.launch(show_api=False, server_port=7872, inbrowser=True)

if __name__ == "__main__":
    main()
