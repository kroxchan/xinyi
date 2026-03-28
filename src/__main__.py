"""xinyi — launcher for `python -m src` or `briefcase`."""
from src.app import build_ui, load_config

def main():
    load_config()
    app = build_ui()
    app.queue()
    app.launch(show_api=False, server_port=7872)

if __name__ == "__main__":
    main()
