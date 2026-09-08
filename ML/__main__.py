"""Start with python -m ML from the repository root."""
from .config import ROOT, Settings


def main() -> None:
    from dotenv import load_dotenv
    import uvicorn
    from .app import create_app

    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                workers=1, ws_max_size=65536, log_level="info")


if __name__ == "__main__":
    main()
