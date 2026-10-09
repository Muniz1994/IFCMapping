"""IFCMapping: fill forms from IFC models with IFCQuery queries.

Run with:  python app.py      (then open http://localhost:8080)
"""
import os
from pathlib import Path

from dotenv import dotenv_values

# Assistant settings (API key, model) from .env. Loaded before importing the app, which reads them
# at import time. Terminal variables win, and empty values are skipped so a blank key doesn't
# hide an `ant auth login` profile.
for key, value in dotenv_values(Path(__file__).parent / ".env").items():
    if value and key not in os.environ:
        os.environ[key] = value

from ifcmapping.ui.app import main  # noqa: E402

if __name__ in {"__main__", "__mp_main__"}:
    main()
