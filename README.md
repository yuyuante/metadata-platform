# Enterprise Metadata Intelligence Platform (EMIP) / 企業中繼資料智能平台（EMIP）

EMIP is an extensible metadata platform for discovering, parsing, normalizing, and persisting metadata from enterprise sources.
EMIP 是一個可擴充的中繼資料平台，用於探索、解析、正規化及保存企業來源的中繼資料。

## Project Overview / 專案概覽

EMIP provides a canonical metadata model and a staged processing flow so scanners and parsers remain independent from persistence. The first release provides a Greenplum-backed vertical slice for SQL DDL files.
EMIP 提供標準化的中繼資料模型與分階段處理流程，使掃描器和解析器能與資料保存機制解耦。第一個版本提供以 Greenplum 為後端的 SQL DDL 檔案垂直切片。

## Features / 功能

- Recursive folder scanning with deterministic ordering / 遞迴掃描資料夾並維持確定性排序
- Canonical `MetadataObject` domain model / 標準化的 `MetadataObject` 領域模型
- SQL DDL parsing through SQLGlot AST / 透過 SQLGlot AST 解析 SQL DDL
- Parser dispatch for supported SQL files / 對支援的 SQL 檔案進行解析器分派
- Greenplum metadata repository and CRUD persistence / Greenplum 中繼資料儲存庫與 CRUD 保存功能
- Command-line scanning with `python -m emip scan <folder>` / 支援以 `python -m emip scan <folder>` 執行命令列掃描
- Ruff, Black, MyPy, pytest, and GitHub Actions CI / 使用 Ruff、Black、MyPy、pytest 及 GitHub Actions CI

## Architecture / 架構

```text
Folder
  ↓
FolderScanner
  ↓
FolderMetadataScanner
  ↓
ParserDispatcher
  ↓
SqlDdlParser
  ↓
MetadataPersister
  ↓
MetadataRepository
  ↓
Greenplum
```

Parsers produce canonical domain objects. They do not access the database directly. The persister delegates storage to the repository boundary.
解析器產生標準化的領域物件，不直接存取資料庫；保存器則透過儲存庫邊界委派資料保存工作。

## Project Structure / 專案結構

```text
src/emip/
├── cli.py
├── database/       # Connection and database naming utilities / 連線與資料庫命名工具
├── domain/         # Canonical metadata objects / 標準化中繼資料物件
├── parser/         # Parser contracts, dispatch, and SQL DDL parser / 解析器契約、分派與 SQL DDL 解析器
├── repository/     # Repository contracts and Greenplum adapters / 儲存庫契約與 Greenplum 配接器
├── scanner/        # File discovery and parser integration / 檔案探索與解析器整合
└── services/       # Application-level pipeline components / 應用程式層級的流程元件

tests/              # Unit and Greenplum integration tests / 單元測試與 Greenplum 整合測試
docs/               # Architecture, design, and project guidance / 架構、設計與專案指引
scripts/sql/        # Greenplum migrations / Greenplum 遷移腳本
```

## Requirements / 系統需求

- Python 3.13 / Python 3.13
- Greenplum 6.x or PostgreSQL-compatible Greenplum environment for persistence / 用於保存資料的 Greenplum 6.x 或相容 PostgreSQL 的 Greenplum 環境
- `uv` preferred; `pip` is supported as a fallback / 建議使用 `uv`；也支援以 `pip` 作為替代方案

## Installation / 安裝

Using uv / 使用 uv：

```powershell
uv sync --extra dev
```

Using pip / 使用 pip：

```powershell
python -m pip install -e ".[dev]"
```

Database connection settings are loaded from `config/database.yaml` or the configured external environment file. Do not commit credentials.
資料庫連線設定會從 `config/database.yaml` 或已設定的外部環境檔案載入。請勿提交憑證。

## Quick Start / 快速開始

Create a folder containing SQL DDL files, for example:
建立一個包含 SQL DDL 檔案的資料夾，例如：

```text
samples/sql/
├── customer.sql
├── order.sql
└── product.sql
```

Each file may contain supported `CREATE TABLE`, `CREATE VIEW`, `CREATE FUNCTION`, `CREATE PROCEDURE`, or `CREATE TRIGGER` statements.
每個檔案可包含支援的 `CREATE TABLE`、`CREATE VIEW`、`CREATE FUNCTION`、`CREATE PROCEDURE` 或 `CREATE TRIGGER` 陳述式。

## Running CLI / 執行命令列工具

```powershell
python -m emip scan samples/sql
```

The command scans files, parses supported SQL DDL, and persists generated metadata objects into Greenplum.
此命令會掃描檔案、解析支援的 SQL DDL，並將產生的中繼資料物件保存至 Greenplum。

## Production Scan / 生產掃描

Use the unified batch entry point from the project root:
請從專案根目錄使用統一批次入口：

```powershell
scripts\scan.bat sql
scripts\scan.bat workflow
scripts\scan.bat all
scripts\scan.bat perf
scripts\scan.bat clean
```

For detailed optional parser profiling, run the CLI with `--profile`:

```powershell
python -m emip scan D:\workplace\infa_fs2\xml --profile
```

The batch entry point accepts the same option for SQL, Workflow, and combined
scans. The `perf` command enables the built-in profiling workflow automatically:

```powershell
scripts\scan.bat sql --profile
scripts\scan.bat workflow --profile
scripts\scan.bat all --profile
scripts\scan.bat perf
```

The profiling summary is printed to the console and written to
`scan-report/performance-report.txt` and the stable JSON companion
`scan-report/performance-report.json`. Every parser can use the same
`Profiler.start("Stage")` / `Profiler.stop("Stage")` API.

The workflow scan defaults to `D:\workplace\infa_fs2\xml` and scans recursively. Set `EMIP_WORKFLOW_ROOT` to override it. The script continues after an individual repository failure, prints each result and a final summary, and returns a non-zero exit code when any scan fails. Missing repositories are reported as skipped. Database settings continue to come from the existing project configuration; credentials are not stored in the batch file.
Workflow 掃描預設使用 `D:\workplace\infa_fs2\xml` 並遞迴掃描；可設定 `EMIP_WORKFLOW_ROOT` 覆寫。批次檔會在單一 repository 失敗後繼續執行，列出每次結果與最終摘要；任一掃描失敗時回傳非零結束碼。不存在的 repository 會列為略過。資料庫設定仍沿用專案既有設定，批次檔不保存憑證。

## Running Tests / 執行測試

```powershell
uv run pytest
```

Or / 或：

```powershell
python -m pytest
```

Quality checks / 品質檢查：

```powershell
uv run ruff check .
uv run black --check .
uv run mypy src
```

## Current Status / 目前狀態

**v0.1.0 — Initial release / 初始版本**

The release provides the first executable scanner-to-Greenplum SQL metadata flow and a generic object-level metadata relationship graph.
此版本提供第一個可執行的「掃描器至 Greenplum SQL 中繼資料」流程，以及通用的物件層級中繼資料關係圖。

## Current Limitations / 目前限制

- Only SQL DDL parsing is implemented / 目前僅實作 SQL DDL 解析
- Unsupported file types are skipped by the dispatcher / 不支援的檔案類型會由分派器略過
- Column-level lineage and impact analysis are not implemented / 尚未實作欄位層級血緣與影響分析
- Workflow, Java, Python, and other language parsers are not implemented / 尚未實作 Workflow、Java、Python 與其他語言的解析器
- Incremental scanning and version persistence are not implemented / 尚未實作增量掃描與版本保存
- REST API, MCP Server, AI, PII detection, and UI are not implemented / 尚未實作 REST API、MCP Server、AI、PII 偵測與使用者介面
- Greenplum configuration must be available to persist metadata / 保存中繼資料時必須提供 Greenplum 設定
- Coverage reporting is not currently configured / 目前尚未設定覆蓋率報告

## Roadmap (v0.2+) / 發展路線圖（v0.2+）

- Parser and scanner plugin hardening / 強化解析器與掃描器外掛機制
- Incremental scan and version history / 增量掃描與版本歷史
- Additional SQL dialect support / 支援更多 SQL 方言
- Informatica and source-code parsers / Informatica 與原始碼解析器
- Column lineage and impact analysis / 欄位血緣與影響分析
- REST API and MCP Server / REST API 與 MCP Server
- PII metadata and AI-ready services / PII 中繼資料與 AI 就緒服務

See [architecture](docs/architecture.md), [coding style](docs/coding-style.md), and [roadmap](docs/roadmap.md) for more detail.
詳細資訊請參閱[架構文件](docs/architecture.md)、[程式碼風格](docs/coding-style.md)與[發展路線圖](docs/roadmap.md)。
