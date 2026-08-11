# EMIP Milestone-003 relation graph design

`EMIP_RELATION` is the minimum graph store: object UUID endpoints, generic relation type, evidence source type, and audit timestamp. Parser candidates retain original SQL and are resolved only after all objects are persisted; unresolved names are discarded, never fabricated. No recursive closure or object-specific relation table is required. Trigger attributes and Dynamic SQL markers use the existing generic property concept.
