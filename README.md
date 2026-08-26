# Enterprise Metadata Intelligence Platform (EMIP) / 企業中繼資料智能平台（EMIP）

EMIP is an extensible, developer-focused metadata intelligence platform for discovering, parsing, normalizing, connecting, querying, and presenting technical metadata from enterprise systems.
EMIP 是一套面向開發人員、可擴充的 Metadata Intelligence Platform，用於探索、解析、正規化、串接、查詢及呈現企業系統中的技術中繼資料。

## Why This Project Exists / 專案緣由

Enterprise data flows are usually distributed across database objects, SQL source files, Informatica PowerCenter repositories, workflow configuration, connection metadata, scripts, and application source code. A developer who needs to answer a simple operational question such as "Where does this table come from?", "Who writes it?", or "What will break if I change it?" often has to search SQL files, inspect Informatica XML, query repository views, grep source code, and ask experienced maintainers.

企業資料流程通常散落在資料庫物件、SQL 原始檔、Informatica PowerCenter Repository、Workflow 設定、Connection Metadata、Script 與應用程式原始碼中。當開發人員想回答「這張表從哪裡來？」「誰寫入它？」「改了它會影響誰？」時，往往必須同時搜尋 SQL、檢查 Informatica XML、查 Repository View、grep 原始碼，甚至依賴資深維護人員的記憶。

EMIP exists to turn that scattered technical knowledge into structured, queryable metadata.
EMIP 的目的，就是把這些分散、依賴人工經驗的技術知識轉成可持續維護、可查詢的 Metadata。

The project addresses several recurring engineering problems:

- **Data lineage is expensive to trace manually.** A physical table may be read or written by SQL, Informatica mappings, sessions, workflows, procedures, views, or downstream jobs.
- **Cross-provider relationships are hard to see.** The same physical object may appear with different names or representations in SQL and Informatica.
- **System knowledge becomes tribal knowledge.** Workflow meaning, source locations, and impact chains are often known only by a small number of maintainers.
- **Impact analysis is slow and risky.** Before changing a table, procedure, mapping, or workflow, developers need to know downstream consumers and upstream dependencies.
- **Finding the original implementation wastes time.** Knowing that an object is related is not enough; developers also need to find the exact SQL file, XML file, source location, and original code or configuration.
- **Developers should not need to understand EMIP repository tables.** The platform should expose searchable, developer-facing queries and a usable web view rather than requiring direct metadata-database SQL.

## Product Goals / 專案目標

EMIP is intended to evolve from a metadata extraction tool into a **Developer Metadata Intelligence Platform**.

The core questions the platform should answer are:

1. **What is it?** — What kind of metadata object is this, and which system/provider owns it?
2. **Where is it?** — Which source file, SQL block, XML element, or repository context defines it?
3. **Where does it come from?** — What upstream objects, mappings, sessions, workflows, or SQL objects feed it?
4. **Where does it go?** — Which downstream objects and processes consume it?
5. **What breaks if I change it?** — What is the bounded impact of modifying this object?

The product direction is:

```text
Technical Metadata
        ↓
Canonical Identity
        ↓
Cross-provider Metadata Graph
        ↓
Data Lineage / Dependency / Impact
        ↓
Source Traceability
        ↓
Developer Query Engine
        ↓
Static Developer Web
        ↓
Processing Logic / Pseudocode
        ↓
AI-assisted Metadata Intelligence
        ↓
Broader Data Governance
```

The short-term product goal is developer-facing exploration: search for an object such as `dbo.STKOUT`, view its bounded upstream/downstream flow, click any node, inspect its source location and original SQL/XML, and navigate dependencies and used-by relationships.

## What EMIP Can Do Today / 目前做得到的事情

### SQL metadata

- Recursively scan supported `.sql` files.
- Parse supported SQL DDL with SQLGlot AST and compatibility handling.
- Materialize supported metadata objects such as `TABLE`, `VIEW`, `MATERIALIZED_VIEW`, `FUNCTION`, `PROCEDURE`, and `TRIGGER` where parser coverage exists.
- Extract and persist object-level metadata, properties, columns where available, source locations, and relationship candidates.
- Build repository relationships used by object, dependency, impact, path, and flow queries.
- Resolve a conservative subset of deterministic dynamic SQL, including literal SQL and simple constant-variable concatenation before `EXEC`, `EXECUTE`, `sp_executesql`, or `EXECUTE IMMEDIATE`.

### Informatica PowerCenter metadata

- Parse PowerCenter XML exports rooted at `POWERMART`.
- Materialize Workflow, Worklet/task nodes, Session, Mapping, Source Definition, Target Definition, Source Qualifier, Lookup, Update Strategy, Command tasks, connections, partitions, and related metadata currently modeled by EMIP.
- Preserve Workflow execution ordering with `PRECEDES` semantics.
- Model Session/Task execution of Mapping metadata with `EXECUTES` semantics.
- Model Mapping source/target relationships with `READS` and `WRITES` semantics.
- Keep source-side and target-side connection metadata independent.
- Resolve representative reusable-session and task-instance cases.
- Persist source traceability back to the originating Informatica XML file and deterministic XML context.
- Retrieve the smallest deterministic XML source context when it can be resolved reliably.

### Cross-provider metadata graph

- Normalize and connect representative SQL and Informatica metadata into one repository graph.
- Resolve supported physical-object identity cases across providers.
- Traverse `READS`, `WRITES`, `EXECUTES`, `PRECEDES`, `REFERENCES`, and other implemented relation types with defined direction.
- Suppress duplicate/self edges at read time for presentation without destructively changing repository data.
- Detect/report dangling, duplicate, self, and cycle conditions in the bounded Data Flow read model.

### Developer queries and source traceability

Repository-only queries do not rescan source files or reparse SQL/XML:

```text
python -m emip query object CUSTOMER
python -m emip query search "cust*"
python -m emip query workflow wf_MB_AC500
python -m emip query impact CUSTOMER --depth 3
python -m emip query depends proc_sync_customer
python -m emip query used-by CUSTOMER
python -m emip query path CUSTOMER ACCOUNT
python -m emip query flow dbo.STKOUT --depth 6
python -m emip query source dbo.STKOUT
python -m emip query search customer --json
```

`flow` returns a deterministic, bounded, cycle-safe upstream/downstream graph. `source` returns persisted SQL or Informatica XML source locations and a bounded source excerpt when it can be resolved reliably. Stable object UUIDs are preserved so individual nodes can be addressed by future consumers and the Developer Web.

### Static Developer Web

The current Milestone-010 work adds a static, browser-only delivery model:

```text
EMIP Repository
    ↓
Static Export
    ↓
Partitioned JSON artifacts
    ↓
HTML + CSS + JavaScript
    ↓
Browser
```

The browser does not connect directly to Greenplum or MSSQL. The intended v1 experience is search → Data Flow → click node → Object Detail → Source Location / Original Code / Dependencies / Used By.

## Capability Boundaries / 能力邊界

EMIP is a **static metadata analysis platform**. It can only claim lineage when the relevant object, SQL text, XML metadata, or static relationship can be determined from available source material. Runtime-only behavior must not be guessed.

The following sections distinguish what is fully supported, partially supported, and currently unsupported.

### 1. Informatica component SQL / Informatica 元件內的 SQL

**Current status: Object-level lineage supported for evidenced properties.**

EMIP extracts the exact, non-empty `Sql Query`, `Lookup Sql Override`, `Pre SQL`,
and `Post SQL` properties observed in PowerCenter `ATTRIBUTE` and
`TABLEATTRIBUTE` elements. It uses the shared SQL statement splitter and
SQLGlot AST parsing (generic SQL, then the known T-SQL, Oracle, and PostgreSQL
production dialects) to derive conservative object-level relations:

- Source Qualifier queries and Lookup overrides create `READS` candidates.
- `SELECT` references in Pre/Post SQL create `READS` candidates.
- `INSERT`, `UPDATE`, `DELETE`, and `MERGE` targets in Pre/Post SQL create
  `WRITES` candidates, while their source tables create `READS` candidates.
- Multi-statement properties retain every safely parsed relation.

Each extracted fragment remains attached to its originating component through
`embedded_sql.*` object properties. Evidence includes the XML file/root,
deterministic XML context, property name, semantic role, raw SQL, connection
when available, analysis status, parse errors, and unresolved references.
Relation candidates also carry this evidence in memory. The current persisted
relation schema stores endpoints, type, and evidence source type but not the
full evidence payload; the originating object's properties and source location
are therefore the durable evidence record.

Physical identity resolution uses the strongest available qualified name and
creates a link only for one unique match. Ambiguous names remain unresolved.
Runtime-dependent object names such as `$$TABLE_NAME` are recorded as
unresolved and never turned into exact lineage. Parameter-file ingestion,
environment-specific resolution, arbitrary SQL-property discovery, and column
lineage remain outside this capability.

For example, if a Source Qualifier contains:

```sql
SELECT a.STOCK_ID
FROM STKOUT a
JOIN TRADE_DATA b
  ON a.STOCK_ID = b.STOCK_ID
```

EMIP creates both `READS → STKOUT` and `READS → TRADE_DATA` candidates from
this override when both physical identities resolve uniquely.

The analyzer creates `READS` candidates for each safely parsed physical object,
provided its identity resolves uniquely during metadata integration.

### 2. Embedded SQL inside application source languages / 程式語言內的 Embedded SQL

**Current status: Not implemented.**

The current parser dispatcher actively dispatches only:

```text
.sql → SqlDdlParser
.xml → InformaticaMetadataParser
```

Parser directories are reserved for additional languages, but Java, Python, C#, C/C++, Shell, Perl, and other source-language parsers are not currently integrated into scanning.

Therefore EMIP does not yet discover embedded SQL such as:

```python
sql = "SELECT * FROM STKOUT"
cursor.execute(sql)
```

```java
String sql = "SELECT * FROM STKOUT";
stmt.executeQuery(sql);
```

```csharp
var cmd = new SqlCommand("SELECT * FROM STKOUT", conn);
```

```bash
psql -c "select * from stkout"
```

or embedded/host-language SQL in C/C++.

Even after language parsers are introduced, there will still be static-analysis limits. For example:

```python
table = get_table_name()
sql = f"SELECT * FROM {table}"
cursor.execute(sql)
```

cannot be resolved exactly unless EMIP can statically determine the return value of `get_table_name()`. Full support would require language AST parsing, constant propagation, string construction analysis, function-call analysis, configuration resolution, and in some cases inter-procedural data flow.

### 3. Dynamic SQL written in SQL languages / SQL Language Dynamic SQL

**Current status: Conservatively and partially supported.**

EMIP includes a `DynamicSqlResolver` designed for deterministic static folding. It intentionally resolves only cases that can be proven from source without runtime execution.

Examples that can be resolved include literal SQL:

```sql
EXEC('SELECT * FROM dbo.STKOUT');
```

and simple constant-variable construction:

```sql
DECLARE @sql VARCHAR(MAX);
SET @sql = 'SELECT * ' + 'FROM dbo.STKOUT';
EXEC(@sql);
```

The resolver supports literal strings, simple variable assignment, and simple `+` / `||` concatenation when all inputs are statically known.

The resolver intentionally returns unresolved when runtime information is required. Examples include:

```sql
SET @sql = 'SELECT * FROM ' + @table_name;
EXEC(@sql);
```

when `@table_name` is not a statically known constant.

The following are not fully supported:

- table or column names derived from procedure parameters;
- values loaded from configuration/database tables at runtime;
- values returned by arbitrary SQL functions;
- general evaluation of `QUOTENAME`, `FORMAT`, `CONCAT`, or arbitrary expressions;
- path-sensitive `IF / ELSE / WHILE / LOOP / CURSOR` dynamic SQL analysis;
- symbolic execution that produces multiple possible lineage branches;
- dynamic SQL assembled across procedure/function call boundaries;
- inter-procedural propagation of SQL strings through parameters;
- runtime-generated temporary table/object names;
- complete column lineage for dynamic projection lists;
- external/environment-dependent SQL text unavailable in the analyzed source.

EMIP should prefer an explicit unresolved result over inventing lineage. A runtime-dependent object name is not equivalent to a proven physical-object relationship.

### 4. Runtime and environment-dependent lineage / 執行期與環境相依血緣

**Current status: Not fully resolvable through static analysis.**

Examples include:

- Informatica parameters loaded from external parameter files not supplied to EMIP;
- SQL object names read from configuration tables;
- application variables populated from environment variables or remote services;
- runtime-generated table names;
- branch-dependent SQL where different conditions target different physical objects;
- SQL downloaded or generated externally at runtime.

These cases need either richer static evidence, configuration ingestion, runtime telemetry, or a confidence/possible-lineage model. EMIP must not silently label a runtime possibility as exact lineage.

### 5. Column-level lineage / 欄位層級血緣

**Current status: Not implemented as a complete end-to-end feature.**

EMIP can persist column metadata where available, but full column-to-column lineage across SQL expressions, mappings, dynamic SQL, Informatica overrides, and application embedded SQL is not yet implemented.

### 6. Unsupported or invalid source / 不支援或無效的來源

- Unsupported file types are skipped by the current dispatcher.
- Invalid SQL is reported; EMIP does not silently repair production source code.
- SQL dialect features unsupported by the underlying parser or compatibility layer may fail parsing.
- Missing source files or ambiguous XML context produce an explicit warning instead of fabricated source output.

## Confidence Model Direction / 未來的解析可信度方向

EMIP should not aim to pretend that 100% of dynamic or embedded SQL can be resolved statically. A more reliable long-term model is to distinguish certainty explicitly, for example:

```text
EXACT
  Static SQL or exact metadata relationship

RESOLVED_DYNAMIC
  Dynamic SQL fully reconstructed from constants

CONDITIONAL / POSSIBLE
  Multiple statically identifiable runtime branches

UNRESOLVED
  Runtime information is required
```

Future relation/evidence models should preserve the original source, resolution method, confidence, and reason for unresolved cases.

## Recommended Analysis Roadmap / 建議解析能力發展順序

The highest-value parser improvements are currently:

1. Add Informatica parameter-file and environment-aware resolution where inputs are available.
2. Extend Dynamic SQL output with confidence/evidence/unresolved-reason metadata.
3. Add Python embedded-SQL parsing using language AST rather than regex.
4. Add Java, C#, C/C++, Shell, and other source-language parsers incrementally.
5. Build column-level lineage only after object-level cross-provider semantics remain stable.

## Project Overview / 專案概覽

EMIP provides a canonical metadata model and a staged processing flow so scanners and parsers remain independent from persistence. It supports SQL DDL and Informatica PowerCenter XML metadata, integrates both providers into one repository graph, and exposes repository-only developer queries.
EMIP 提供標準化的中繼資料模型與分階段處理流程，使掃描器和解析器能與資料保存機制解耦。目前支援 SQL DDL 與 Informatica PowerCenter XML 中繼資料，將兩種 Provider 整合至同一 Repository Graph，並提供只查詢 Repository 的開發者命令列工具。

## Features / 功能

- Recursive folder scanning with deterministic ordering / 遞迴掃描資料夾並維持確定性排序
- Canonical `MetadataObject` domain model / 標準化的 `MetadataObject` 領域模型
- SQL DDL parsing through SQLGlot AST / 透過 SQLGlot AST 解析 SQL DDL
- Informatica PowerCenter XML workflow and mapping metadata parsing / 解析 Informatica PowerCenter XML Workflow 與 Mapping 中繼資料
- Cross-provider physical-object identity resolution / 跨 Provider 實體物件識別
- Repository-only object, workflow, impact, dependency, path, flow, and source queries / 只透過 Repository 執行物件、Workflow、影響、相依性、路徑、Data Flow 與 Source 查詢
- Browser-only static Developer Web export / 不需後端服務的靜態 Developer Web 匯出
- Optional reusable scan profiling with `--profile` / 以 `--profile` 啟用可重用的選擇性掃描效能分析
- Greenplum metadata repository and CRUD persistence / Greenplum 中繼資料儲存庫與 CRUD 保存功能
- Ruff, Black, MyPy, pytest, and GitHub Actions CI / 使用 Ruff、Black、MyPy、pytest 及 GitHub Actions CI

## Architecture / 架構

```text
Folder / Informatica XML
  ↓
FolderScanner
  ↓
FolderMetadataScanner
  ↓
ParserDispatcher
  ↓
SqlDdlParser / InformaticaMetadataParser
  ↓
MetadataIntegration
  ↓
MetadataPersister
  ↓
MetadataRepository
  ↓
Greenplum
  ↓
Query Engine / Data Flow / Source Traceability
  ↓
Static Developer Web Export
```

Parsers produce canonical domain objects. They do not access the database directly. The persister delegates storage to the repository boundary.
解析器產生標準化的領域物件，不直接存取資料庫；保存器則透過儲存庫邊界委派資料保存工作。

## Project Structure / 專案結構

```text
src/emip/
├── cli.py
├── database/       # Connection and database naming utilities / 連線與資料庫命名工具
├── domain/         # Canonical metadata objects / 標準化中繼資料物件
├── parser/         # SQL, Informatica, dynamic-SQL analysis, and parser contracts
├── repository/     # Repository contracts and Greenplum adapters / 儲存庫契約與 Greenplum 配接器
├── scanner/        # File discovery and parser integration / 檔案探索與解析器整合
├── services/       # Integration, query, Data Flow, traceability / 整合、查詢、資料流與追溯
└── web/            # Static Developer Web exporter and assets / 靜態 Developer Web 匯出器與資產

tests/              # Unit and Greenplum integration tests / 單元測試與 Greenplum 整合測試
docs/               # Architecture, design, and project guidance / 架構、設計與專案指引
scripts/sql/        # Greenplum migrations / Greenplum 遷移腳本
```

## Requirements / 系統需求

- Python 3.13
- Greenplum 6.x or PostgreSQL-compatible Greenplum environment for persistence
- `uv` preferred; `pip` supported as fallback

Database connection settings are loaded from `config/database.yaml` or the configured external environment file. Do not commit credentials.

## Installation / 安裝

Using uv / 使用 uv：

```powershell
uv sync --extra dev
```

Using pip / 使用 pip：

```powershell
python -m pip install -e ".[dev]"
```

## Production Scan / 生產掃描

Use the unified batch entry point from the project root:

```powershell
scripts\scan.bat sql
scripts\scan.bat workflow
scripts\scan.bat all
scripts\scan.bat perf
scripts\scan.bat clean
```

For detailed profiling:

```powershell
python -m emip scan D:\workplace\infa_fs2\xml --profile
```

The profiling summary is written to `scan-report/performance-report.txt` and `scan-report/performance-report.json`.

## Static Developer Web / 靜態開發者網頁

Export the existing repository to a browser-only site:

```powershell
python -m emip web export
python -m emip web export --output web-dist --depth 6
python -m http.server 8000 --directory web-dist
```

Then open `http://localhost:8000`. The browser reads generated artifacts only and does not connect directly to Greenplum.

Search uses a compact startup manifest and lazy three-character token-prefix
shards, choosing the smallest shard represented in a multi-token query, so the
browser does not load the complete repository catalog before its first useful
interaction. Explicit **Explore from selection** actions create
`#object=<stable-object-id>` history entries that work with browser Back/Forward.

See [Static Developer Web](docs/emip/developer-web.md) for the output contract and deployment notes.

## Running Tests / 執行測試

```powershell
uv run pytest
uv run ruff check .
uv run black --check .
uv run mypy src
```

## Current Status / 目前狀態

The project currently has production SQL/Informatica scanning, canonical object identity, cross-provider integration, repository graph queries, bounded Data Flow, source traceability, deterministic source retrieval, scan profiling/performance optimization, and an in-progress Static Developer Web v1.

The platform is already useful for **object-level technical metadata and developer data-flow exploration**, but it should not yet be described as a complete universal SQL lineage engine, complete Informatica SQL analyzer, embedded-SQL analyzer, or end-to-end column-lineage engine.

## Current Limitations / 目前限制

- Informatica SQL-property lineage is object-level and limited to the four
  evidenced property names documented above; parameterized object names remain
  unresolved without environment inputs.
- Java, Python, C#, C/C++, Shell, Perl, and other embedded-SQL source-language parsers are not implemented.
- Dynamic SQL is limited to deterministic static folding; runtime-dependent cases remain unresolved.
- Complete column-level lineage and impact analysis are not implemented.
- Incremental scanning and metadata version persistence are not implemented.
- REST API, MCP Server, AI/LLM analysis, PII detection, and server-backed UI are not implemented.
- Invalid or unsupported SQL is reported rather than silently repaired.
- Runtime/environment-dependent lineage cannot be proven without the required external evidence.

## Roadmap / 發展路線圖

- Complete Milestone-010 Static Developer Web v1.
- Informatica parameter/environment resolution.
- Confidence/evidence-aware dynamic SQL lineage.
- Source-language AST parsers for Python, Java, C#, C/C++, Shell, and others.
- Column-level lineage and richer impact analysis.
- Incremental scans and metadata version history.
- REST API / MCP Server where justified by product use cases.
- AI-assisted processing-logic explanation and metadata intelligence after deterministic metadata foundations are stable.
- PII/classification/governance capabilities as later platform layers.

See [architecture](docs/architecture.md), [Data Flow and Source Traceability](docs/emip/data-flow.md), [Static Developer Web](docs/emip/developer-web.md), and [roadmap](docs/roadmap.md) for more detail.
