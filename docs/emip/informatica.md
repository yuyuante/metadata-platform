# Informatica metadata extraction / Informatica 中繼資料擷取

## Supported XML objects / 已支援 XML 物件

The PowerCenter XML parser recursively scans exported `POWERMART` documents and creates canonical `MetadataObject` records for folders, workflows, schedulers, workflow variables and attributes, task instances, sessions, mappings, source and target definitions, transformations, session configuration, partitions, connections, and command values.

PowerCenter XML 解析器會遞迴掃描 `POWERMART` 文件，建立資料夾、工作流程、排程器、工作流程變數與屬性、工作項目、Session、Mapping、來源與目標定義、轉換、Session 設定、分割、連線及命令值等標準 `MetadataObject`。

Workflow links are persisted as `EXECUTES` candidates. Their original XML element is retained as evidence, and link conditions are stored as object properties; conditions are not evaluated.

WorkflowLink 以 `EXECUTES` 候選關係保存，並保留包含 `CONDITION` 的原始 XML 元素作為證據；不進行條件判斷。

## Unsupported objects and limitations / 未支援物件與限制

- Runtime monitor state, deployment state, and repository database-only metadata are not inferred.
- Command text is stored and is never executed.
- Transformation-level lineage and column lineage are not implemented in this milestone.
- References that cannot be identified by deterministic XML names are not guessed.
- Namespaces and PowerCenter export encodings are accepted when declared by the XML document.

- 不推導執行期監控狀態、部署狀態及僅存在於 Repository database 的中繼資料。
- 命令文字只保存，不執行。
- 本里程碑不實作轉換層級 lineage 與欄位 lineage。
- 無法由 XML 名稱確定的參照不猜測。
- 支援 XML 文件宣告的編碼與 namespace。