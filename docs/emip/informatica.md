# Informatica metadata extraction / Informatica 中繼資料擷取

## Supported XML objects / 已支援 XML 物件

The PowerCenter XML parser recursively scans exported `POWERMART` documents and creates canonical `MetadataObject` records for folders, workflows, schedulers, workflow variables and attributes, task instances, sessions, mappings, source and target definitions, transformations, session configuration, partitions, connections, and command values.

PowerCenter XML 解析器會遞迴掃描 `POWERMART` 文件，建立資料夾、工作流程、排程器、工作流程變數與屬性、工作項目、Session、Mapping、來源與目標定義、轉換、Session 設定、分割、連線及命令值等標準 `MetadataObject`。

Session-to-mapping links are persisted as `EXECUTES` candidates. Workflow links between tasks are persisted as `PRECEDES` candidates, meaning the source task runs before the target task. Their original XML element is retained as evidence, and link conditions are stored as object properties; conditions are not evaluated.

Task 執行 Mapping 的關係以 `EXECUTES` 候選關係保存；WorkflowLink 則以 `PRECEDES` 候選關係保存，表示來源 Task 先於目標 Task 執行。兩者均保留包含 `CONDITION` 的原始 XML 元素作為證據；不進行條件判斷。

Parallel tasks remain siblings in the workflow structure. A merge or join point
is represented by multiple incoming `PRECEDES` relations; it is not displayed as
a parent/child hierarchy. `READS` represents source-side access and retains the
source connection, while `WRITES` represents target-side output and retains the
target connection. Source and target connections are resolved independently.
Command Task text, parameter files, output files, and merge files are retained as
metadata and are never executed by EMIP.

平行 Task 在 Workflow 結構中維持同層；匯合點以多條傳入的 `PRECEDES` 關係表示，不轉換成父子階層。`READS` 表示來源端讀取並保留 Source Connection，`WRITES` 表示目標端輸出並保留 Target Connection，兩端連線會獨立解析。Command Task 指令、參數檔、輸出檔及合併檔均只保存為中繼資料，不由 EMIP 執行。

## Transformation-port column lineage

The parser supports the PowerCenter 10.2 structures evidenced by repository fixtures
and bounded production samples: folder-level `SOURCE/SOURCEFIELD` and
`TARGET/TARGETFIELD`, plus mapping-level `INSTANCE`,
`TRANSFORMATION/TRANSFORMFIELD`, and `CONNECTOR`. Observed `TRANSFORMFIELD` records
provide `NAME`, `PORTTYPE`, and optional `EXPRESSION`; connector endpoints provide
`FROMINSTANCE/FROMFIELD` and `TOINSTANCE/TOFIELD`. Session
`SESSTRANSFORMATIONINST`, `SESSIONEXTENSION`, and `CONNECTIONREFERENCE` records retain
independent source, target, and lookup connection context.

One mapping-scoped index is built for instances, transformation fields, and incoming
connectors. A port identity is `mapping + instance + field`, so equal short port names
in separate transformations never collide. Duplicate instances, duplicate
transformation fields, missing endpoints, ambiguous connectors, cycles, and bounded
graph-limit failures are withheld from exact lineage rather than guessed.

Supported behavior is deliberately dependency analysis, not PowerCenter execution:

- Source Qualifier, Router, Filter, and Update Strategy ports preserve
  `EXACT_DIRECT` identity when exactly one connector proves the pass-through path.
- Expression and Aggregator outputs become `EXACT_EXPRESSION` only when every
  referenced input port resolves exactly. Multi-input dependencies are all retained;
  constants create no source-column dependency. Expressions are tokenized for port
  references and are never evaluated.
- Lookup outputs are exact only when their XML expression explicitly proves the input
  dependency. Implicit lookup returns and ambiguous conditions remain `UNRESOLVED`.
- Unsupported transformation types remain local unresolved findings and do not stop
  unrelated mappings from parsing.

The final candidate uses the existing physical `ColumnLineageCandidate` and
`ColumnLineage` graph. Internal Informatica ports are not persisted as fake database
objects. Exact physical lineage requires independently resolved, provider-aware source
and target objects and loaded matching columns. The persisted evidence contains the
mapping, complete transformation/instance path, connectors, expression, XML source,
and independent source/target/lookup connections. `query column-lineage` reads this
persisted evidence without reparsing XML and exposes it as structured `informatica`
data. Repeated persistence remains UUIDv5-idempotent and uses no PostgreSQL
`ON CONFLICT` syntax.

All XML names, ports, expressions, paths, and evidence are inert untrusted text. EMIP
does not evaluate expressions, execute commands or SQL, or derive filesystem commands
from metadata. Traversal is cycle-safe and capped at 512 ports per path, 10,000
transformation ports, 20,000 connectors, and 10,000 persisted records per mapping.
Future Static Web rendering must continue to use escaped text/`textContent`.

## Unsupported objects and limitations / 未支援物件與限制

- Runtime monitor state, deployment state, and repository database-only metadata are not inferred.
- Command text is stored and is never executed.
- PowerCenter runtime semantics, branch reachability, sequence generators, Java/custom
  transformations, implicit lookup return semantics, and a broad PowerCenter
  expression runtime are not inferred.
- References that cannot be identified by deterministic XML names are not guessed.
- Namespaces and PowerCenter export encodings are accepted when declared by the XML document.

- 不推導執行期監控狀態、部署狀態及僅存在於 Repository database 的中繼資料。
- 命令文字只保存，不執行。
- 不推導 PowerCenter 執行期語意、分支可達性、未明確 Lookup 回傳依賴或完整
  PowerCenter expression runtime；缺乏確切證據時保留為 `UNRESOLVED`。
- 無法由 XML 名稱確定的參照不猜測。
- 支援 XML 文件宣告的編碼與 namespace。
