# IFCMapping

Fill form parameters (e.g. the INE *Edificação e Demolição* XML form) from an IFC model, using [IFCQuery](https://github.com/Muniz1994/IFCQuery) queries. Includes a query editor with live validation and autocompletion, and an optional AI assistant that proposes queries.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Run

```powershell
.venv\Scripts\python app.py
```

Then open http://localhost:8080 in your browser. Stop the app with **Ctrl+C**.

If you activate the virtual environment first (`.venv\Scripts\Activate.ps1`), `python app.py` is enough.

## Assistant (optional)

The assistant panel needs an Anthropic API key. Put it in a `.env` file in the project folder (copy `.env.example` if `.env` doesn't exist):

```ini
ANTHROPIC_API_KEY=sk-ant-...
IFCMAPPING_MODEL=claude-opus-5-5     # or claude-sonnet-5-5 (cheaper)
IFCMAPPING_EFFORT=medium             # low, medium or high
```

Restart the app after editing `.env`. `.env` is not committed to git.

Variables set in the terminal take precedence over `.env`, e.g. `$env:ANTHROPIC_API_KEY = "sk-ant-..."` before `python app.py`.

## Tests

```powershell
.venv\Scripts\python -m pytest
```
