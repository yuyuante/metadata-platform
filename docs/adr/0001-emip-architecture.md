# ADR-0001：Enterprise Metadata Intelligence Platform Architecture

## Status

Accepted

## Date

2026-08-10

## Context

EMIP（Enterprise Metadata Intelligence Platform）旨在建立一套可長期維護的企業級 Metadata 平台，支援 Source Code、ETL、Database、File、API、FTP 與未來其他 Metadata 來源。

平台必須支援 Metadata Repository、Table Lineage、Column Lineage、Impact Analysis、Incremental Scan、Version History、Sensitive Data Discovery、AI Copilot 與 MCP Server，並且能持續擴充，不因新增 Parser 或資料來源而修改核心架構。

## Architecture Principles

### 1. Canonical Metadata Model

所有 Parser 都必須輸出同一套 Canonical Metadata Model。Parser 禁止直接寫入資料庫，只負責產出 ParsedObject、ParsedColumn、ParsedRelation 與 ParsedProperty；Repository 負責 Persistence、Version、Transaction 與 Incremental Update。

### 2. Repository Pattern

所有資料存取都必須經過 Repository。Parser、Scanner 與 Service 不得直接執行 SQL 或操作資料表，Database Access 集中由 Repository 管理。

### 3. Plugin Architecture

Scanner、Parser、Repository 與 AI Provider 均採 Plugin 架構。新增 Folder、Git、FTP、Database scanner，SQL、Informatica、Java、Python、Shell、C#、C++、Perl parser，Greenplum、MSSQL、PostgreSQL repository，或 OpenAI、Local LLM、Azure OpenAI、Anthropic、Gemini provider 時，不得修改 Core。

### 4. Incremental First

EMIP 以 Incremental Scan 為預設：Scanner 計算 Hash、比較前一版本，只解析變更的物件，最後由 Repository 更新資料。

### 5. Immutable Version

Metadata 永遠保留歷史版本，不覆蓋既有版本。每次修改都建立新的 Version，支援 Version Compare、Rollback、Historical Lineage 與 Historical Impact Analysis。

### 6. Database Independence

Core 不依賴任何資料庫。Repository 使用 Database Dialect，例如 GreenplumDialect、MSSQLDialect 與 PostgreSQLDialect，以便未來替換資料庫而不修改 Core。

### 7. AI Independence

AI 不是 Core，而是 Consumer。EMIP 提供 REST API 與 MCP Server，AI 透過 API 查詢 Metadata，不得直接存取資料庫。

### 8. Sensitive Data as Metadata

PII 規則資料化，不寫死於程式。規則支援新增、停用、版本與自訂分類；Detection Method 包括 Metadata、Comment、Regex、Sample 與 AI。

### 9. Graph Independence

第一版使用 Greenplum Repository，Graph Query 使用 Recursive CTE。若未來效能不足，再導入 Graph Database；Core 不依賴任何 Graph Engine。

### 10. Clean Architecture

依賴方向固定為：

```text
Scanner → Parser → Metadata Model → Repository → Service → REST API / MCP → AI / UI
```

任何下層不得依賴上層。

## Out of Scope

目前不實作 SQL Parser、Informatica Parser、Java Parser、AI、Web UI、Dashboard 或 Neo4j，將於後續 Sprint 完成。

## Consequences

此架構提供高可維護性、Plugin 擴充能力、Incremental Update、Version History、AI Ready、Database Independence 與長期可演進能力。EMIP 的核心價值是 Metadata，而非特定 Parser 或 AI 模型。