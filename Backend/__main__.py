"""Run from the repository root: python -m Backend."""
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

from .config import Settings
from .app import create_app


def main():
    load_dotenv(Path(__file__).with_name('.env'), override=False, interpolate=False)
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                ws_max_size=16384, log_level='info')


if __name__ == '__main__':
    main()
