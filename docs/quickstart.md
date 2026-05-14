# Quickstart

This guide targets Windows, Python 3.12, and PowerShell.

## 1. Create a Virtual Environment

Run from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
```

## 2. Install Dependencies

```powershell
.\.venv\Scripts\pip install -r requirements.txt
```

## 3. Create Local Configuration

```powershell
Copy-Item .env.example .env
```

The default service address is:

```text
http://127.0.0.1:8002
```

## 4. Initialize an Empty Database

```powershell
.\.venv\Scripts\python scripts\init_empty_db.py
```

This creates local runtime folders, runs database migrations, and inserts a default zero-balance account.

## 5. Start the Service

```powershell
.\scripts\run_local.ps1
```

Open:

```text
http://127.0.0.1:8002
```

Check service health:

```text
http://127.0.0.1:8002/health
```
