# EMIP Milestone-003 relation graph design

`EMIP_RELATION` is the minimum graph store: object UUID endpoints, generic relation type, evidence source type, and audit timestamp. Parser candidates retain original SQL and are resolved only after all objects are persisted; unresolved names are discarded, never fabricated. No recursive closure or object-specific relation table is required. Trigger attributes and Dynamic SQL markers use the existing generic property concept.

`contains_dynamic_sql=true` always preserves `dynamic_sql_source`; `dynamic_sql_status` is `RESOLVED` only for a complete literal or a variable assigned a complete literal. Concatenated, generated, and table-loaded SQL remains `UNRESOLVED`. Trigger `UPDATE OF` columns are stored as the `trigger_update_columns` generic property when every item is syntactically identifiable.

`RelationGraphService` performs cycle-safe breadth-first upstream or downstream traversal over direct repository edges. `max_depth` limits expansion and does not add persisted closure rows.
