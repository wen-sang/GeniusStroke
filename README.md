# GeniusStroke

GeniusStroke is a local investment data dashboard and API service for market data, fundamentals, indicators, portfolio positions, orders, and account views.

The first release target is Windows with Python 3.12 and PowerShell.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).

## Quick Start

Run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python scripts\init_empty_db.py
.\scripts\run_local.ps1
```

Then open:

```text
http://127.0.0.1:8002
```

Health check:

```text
http://127.0.0.1:8002/health
```

## Configuration

Local configuration lives in `.env`. The default settings bind only to `127.0.0.1:8002`.

External data source tokens are optional for basic startup. Features that require a token will only work after you fill the related variable in `.env`, such as `LIXINREN_TOKEN`.

## Local Check

After the service starts, you can run:

```powershell
.\scripts\check_local.ps1
```

More setup details are in [docs/quickstart.md](docs/quickstart.md) and [docs/configuration.md](docs/configuration.md).
