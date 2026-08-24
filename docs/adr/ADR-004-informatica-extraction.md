# ADR-004: Informatica XML metadata extraction

- Status: Accepted
- Date: 2026-08-12

## Decision

Use a dedicated PowerCenter XML parser and the existing `MetadataObject` and `RelationCandidate` model. XML is parsed recursively by element name, with the source XML fragment retained as relationship evidence. The parser creates deterministic metadata only; it does not execute commands, evaluate workflow conditions, or infer runtime lineage.

採用獨立的 PowerCenter XML 解析器，重用既有 `MetadataObject` 與 `RelationCandidate` 模型。XML 依元素名稱遞迴解析，關係保留來源 XML 片段作為證據。解析器只建立可由 XML 確定的中繼資料，不執行命令、不評估工作流程條件，也不推導執行期 lineage。

## Rationale

A separate parser isolates Informatica-specific XML structure from the production SQL parser and prevents dialect-specific assumptions from leaking into SQL extraction. Deterministic names provide stable identities across renamed export files and allow the existing repository deduplication and relation resolution to be reused.

獨立解析器可將 Informatica 專屬 XML 結構與 production SQL parser 隔離，避免平台差異污染 SQL 擷取。使用確定性的名稱建立穩定 identity，可重用既有 Repository 去重與關係解析。