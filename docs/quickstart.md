# 快速开始

本文面向 Windows、Python 3.12 和 PowerShell 环境。

## 1. 创建虚拟环境

在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
```

## 2. 安装依赖

```powershell
.\.venv\Scripts\pip install -r requirements.txt
```

## 3. 创建本地配置

```powershell
Copy-Item .env.example .env
```

默认服务地址是：

```text
http://127.0.0.1:8002
```

## 4. 初始化空数据库

```powershell
.\.venv\Scripts\python scripts\init_empty_db.py
```

该命令会创建本地运行目录，执行数据库迁移，并写入一个默认的零余额账户。

## 5. 启动服务

```powershell
.\scripts\run_local.ps1
```

打开：

```text
http://127.0.0.1:8002
```

健康检查：

```text
http://127.0.0.1:8002/health
```
