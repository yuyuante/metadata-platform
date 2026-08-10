# Repository Layer

The repository layer is the persistence boundary for metadata objects and relations. The core package defines abstract interfaces for saving, updating, deleting, and finding objects, as well as upstream and downstream relationship queries.

Database-specific implementations are intentionally deferred. Sprint 0 contains no SQL, Greenplum, MSSQL, or other database code.