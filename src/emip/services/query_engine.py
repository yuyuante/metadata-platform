"""Repository-only developer queries over the EMIP metadata graph."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterator, Mapping, Sequence
from fnmatch import fnmatchcase
from typing import Protocol, cast
from uuid import UUID

from emip.domain import MetadataObject, ObjectType, Relation, RelationType
from emip.services.data_flow import DataFlowService
from emip.services.dynamic_sql_details import dynamic_sql_details
from emip.services.source_traceability import SourceTraceabilityService


class QueryRepository(Protocol):
    """Minimal read-only repository contract used by the query engine."""

    def find_objects(self) -> list[MetadataObject]: ...

    def find_relations(self) -> list[Relation]: ...


def _identity(value: str) -> str:
    """Normalize common SQL identifier quoting for logical comparisons."""

    parts = value.strip().split(".")
    cleaned = []
    for part in parts:
        item = part.strip()
        if len(item) >= 2 and item[0] == item[-1] and item[0] in '"`':
            item = item[1:-1]
        if item.startswith("[") and item.endswith("]"):
            item = item[1:-1]
        cleaned.append(item.strip().lower())
    return ".".join(cleaned)


def _qualified_parts(qualified_name: str) -> tuple[str, str]:
    parts = [part for part in qualified_name.split(".") if part]
    if len(parts) >= 3:
        return parts[-3], parts[-2]
    if len(parts) == 2:
        return "", parts[-2]
    return "", ""


def _object_dict(item: MetadataObject) -> dict[str, object]:
    database, schema = _qualified_parts(item.qualified_name)
    result: dict[str, object] = {
        "object_type": item.object_type.value,
        "qualified_name": item.qualified_name,
        "schema": schema,
        "database": database,
        "provider": item.system_name,
        "description": item.description,
        "object_id": str(item.object_id),
        "properties": {
            prop.property_name: prop.property_value for prop in item.properties
        },
    }
    dynamic_sql = dynamic_sql_details(item)
    if dynamic_sql is not None:
        result["dynamic_sql"] = dynamic_sql
    return result


def _relation_dict(relation: Relation) -> dict[str, object]:
    return {
        "relation_type": str(relation.relation_type),
        "source_object_id": str(relation.source_object_id),
        "target_object_id": str(relation.target_object_id),
        "source_type": relation.source_type,
    }


def _connection_property_value(item: MetadataObject) -> str | None:
    """Return a useful DB connection name from provider-specific properties."""

    connection_keys = {
        "connection",
        "connectionname",
        "dbconnection",
        "dbconnectionname",
        "connectionreferenceconnectionname",
        "connectionreferencename",
    }
    for prop in item.properties:
        key = "".join(
            character for character in prop.property_name.lower() if character.isalnum()
        )
        if key in connection_keys and prop.property_value:
            return prop.property_value
    return None


class QueryEngine:
    """Execute developer queries against already persisted metadata only."""

    def __init__(self, repository: QueryRepository) -> None:
        self._repository = repository
        self._objects = repository.find_objects()
        self._by_id = {item.object_id: item for item in self._objects}
        self._relations = repository.find_relations()
        self._outgoing: dict[UUID, list[Relation]] = defaultdict(list)
        self._incoming: dict[UUID, list[Relation]] = defaultdict(list)
        for relation in self._relations:
            if (
                relation.source_object_id in self._by_id
                and relation.target_object_id in self._by_id
                and relation.source_object_id != relation.target_object_id
            ):
                self._outgoing[relation.source_object_id].append(relation)
                self._incoming[relation.target_object_id].append(relation)

    def _connection_label(
        self, object_id: UUID, relation_type: RelationType | None = None
    ) -> str | None:
        """Resolve the connection for a definition and its data direction.

        Informatica stores the connection on the session's reader/writer
        connection object rather than on every Source/Target Definition.  A
        definition-local value wins; otherwise use only a matching reader,
        lookup, or writer child of its owning session.  This prevents a
        writer connection from being reported on a READS edge.
        """

        item = self._by_id.get(object_id)
        if item is None:
            return None
        direct = _connection_property_value(item)
        if direct:
            return direct
        if item.object_type == ObjectType.CONNECTION:
            return item.qualified_name
        if item.object_type is ObjectType.SESSION:
            session_connection_names: list[str] = []
            for relation in self._outgoing.get(object_id, []):
                if relation.relation_type is not RelationType.BELONGS_TO:
                    continue
                child = self._by_id.get(relation.target_object_id)
                if child is None:
                    continue
                if (
                    relation_type is RelationType.READS
                    and child.object_type is ObjectType.SOURCE_DEFINITION
                ) or (
                    relation_type is RelationType.WRITES
                    and child.object_type is ObjectType.TARGET_DEFINITION
                ):
                    value = _connection_property_value(child)
                    if value:
                        session_connection_names.append(value)
            if len(set(session_connection_names)) == 1:
                return session_connection_names[0]
        if item.object_type is ObjectType.MAPPING:
            mapping_connection_names: list[str] = []
            for relation in self._incoming.get(object_id, []):
                if relation.relation_type is not RelationType.EXECUTES:
                    continue
                task = self._by_id.get(relation.source_object_id)
                if task is None or task.object_type is not ObjectType.SESSION:
                    continue
                for child_relation in self._outgoing.get(task.object_id, []):
                    if child_relation.relation_type is not RelationType.BELONGS_TO:
                        continue
                    child = self._by_id.get(child_relation.target_object_id)
                    if child is None:
                        continue
                    if (
                        relation_type is RelationType.READS
                        and child.object_type is ObjectType.SOURCE_DEFINITION
                    ):
                        value = _connection_property_value(child)
                        if value:
                            mapping_connection_names.append(value)
                    elif (
                        relation_type is RelationType.WRITES
                        and child.object_type is ObjectType.TARGET_DEFINITION
                    ):
                        value = _connection_property_value(child)
                        if value:
                            mapping_connection_names.append(value)
            if len(set(mapping_connection_names)) == 1:
                return mapping_connection_names[0]
        sessions = [
            self._by_id[relation.source_object_id]
            for relation in self._incoming.get(object_id, [])
            if relation.relation_type is RelationType.BELONGS_TO
            and relation.source_object_id in self._by_id
            and self._by_id[relation.source_object_id].object_type is ObjectType.SESSION
        ]
        connection_objects: list[MetadataObject] = []
        for session in sessions:
            for relation in self._outgoing.get(session.object_id, []):
                if relation.relation_type is not RelationType.BELONGS_TO:
                    continue
                child = self._by_id.get(relation.target_object_id)
                if child is None or child.object_type is not ObjectType.CONNECTION:
                    continue
                label = child.qualified_name.lower()
                is_reader = "reader" in label or "lookup" in label
                is_writer = "writer" in label
                if relation_type is RelationType.READS and is_reader:
                    connection_objects.append(child)
                elif relation_type is RelationType.WRITES and is_writer:
                    connection_objects.append(child)
        labels = {
            _connection_property_value(item) or item.qualified_name
            for item in connection_objects
        }
        return next(iter(labels)) if len(labels) == 1 else None

    def resolve(self, term: str) -> MetadataObject:
        """Resolve an exact object name or qualified name."""

        try:
            object_id = UUID(term)
        except ValueError:
            object_id = None
        if object_id is not None and object_id in self._by_id:
            return self._by_id[object_id]

        wanted = _identity(term)
        qualified_matches = [
            item for item in self._objects if _identity(item.qualified_name) == wanted
        ]
        matches = qualified_matches or [
            item for item in self._objects if _identity(item.name) == wanted
        ]
        if not matches:
            raise ValueError(f"Object not found: {term}")
        physical_types = {
            ObjectType.TABLE,
            ObjectType.VIEW,
            ObjectType.MATERIALIZED_VIEW,
        }
        preferred = [item for item in matches if item.object_type in physical_types]
        if preferred:
            matches = preferred
        if len(matches) > 1:
            names = ", ".join(item.qualified_name for item in matches[:5])
            raise ValueError(f"Object is ambiguous: {term} ({names})")
        return matches[0]

    def object_lookup(self, term: str) -> dict[str, object]:
        return _object_dict(self.resolve(term))

    def flow(self, term: str, depth: int = 6) -> dict[str, object]:
        """Return a deterministic, bounded semantic data-flow projection."""

        return (
            DataFlowService()
            .build(self.resolve(term), self._objects, self._relations, depth)
            .to_dict()
        )

    def source(self, term: str) -> dict[str, object]:
        """Return persisted source pointers and bounded source excerpts."""

        return SourceTraceabilityService().retrieve(self.resolve(term))

    def search(self, term: str) -> list[dict[str, object]]:
        pattern = _identity(term)
        has_wildcard = "*" in pattern or "?" in pattern
        result: list[dict[str, object]] = []
        for item in self._objects:
            candidates = (_identity(item.name), _identity(item.qualified_name))
            matched = any(
                (
                    fnmatchcase(candidate, pattern)
                    if has_wildcard
                    else pattern in candidate
                )
                for candidate in candidates
            )
            if matched:
                result.append(
                    {
                        "object_type": item.object_type.value,
                        "qualified_name": item.qualified_name,
                        "provider": item.system_name,
                    }
                )
        return result

    def _walk(
        self, start: UUID, outgoing: bool, depth: int
    ) -> list[tuple[MetadataObject, int]]:
        edges = self._outgoing if outgoing else self._incoming
        queue: deque[tuple[UUID, int]] = deque([(start, 0)])
        seen = {start}
        result: list[tuple[MetadataObject, int]] = []
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for relation in edges.get(current, []):
                next_id = (
                    relation.target_object_id if outgoing else relation.source_object_id
                )
                if next_id in seen or next_id not in self._by_id:
                    continue
                seen.add(next_id)
                next_depth = current_depth + 1
                result.append((self._by_id[next_id], next_depth))
                queue.append((next_id, next_depth))
        return result

    def impact(self, term: str, depth: int = 1) -> dict[str, list[dict[str, object]]]:
        if depth < 1:
            raise ValueError("--depth must be at least 1")
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item, item_depth in self._walk(self.resolve(term).object_id, False, depth):
            group = {
                ObjectType.VIEW: "Views",
                ObjectType.FUNCTION: "Functions",
                ObjectType.PROCEDURE: "Procedures",
                ObjectType.TRIGGER: "Triggers",
                ObjectType.MAPPING: "Mappings",
                ObjectType.WORKFLOW: "Workflows",
            }.get(item.object_type, item.object_type.value)
            data = _object_dict(item)
            data["depth"] = item_depth
            grouped[group].append(data)
        return dict(sorted(grouped.items()))

    def depends(self, term: str, depth: int = 999999) -> list[dict[str, object]]:
        return self._walk_result(term, True, depth)

    def used_by(self, term: str, depth: int = 999999) -> list[dict[str, object]]:
        return self._walk_result(term, False, depth)

    def _walk_result(
        self, term: str, outgoing: bool, depth: int
    ) -> list[dict[str, object]]:
        if depth < 1:
            raise ValueError("--depth must be at least 1")
        return [
            {**_object_dict(item), "depth": item_depth}
            for item, item_depth in self._walk(
                self.resolve(term).object_id, outgoing, depth
            )
        ]

    def workflow(self, term: str) -> dict[str, object]:
        try:
            root = self.resolve(term)
        except ValueError as error:
            # Informatica schedulers are stored with the generic object name
            # ``Scheduler`` while the workflow name is the final segment of
            # their qualified name.  Resolve that user-facing workflow name
            # only for this command; ordinary object lookup remains exact.
            wanted = _identity(term)
            workflow_matches = [
                item
                for item in self._objects
                if item.object_type in {ObjectType.WORKFLOW, ObjectType.SCHEDULER}
                and _identity(item.qualified_name.rsplit("::", 1)[-1]) == wanted
            ]
            if not workflow_matches:
                raise error
            if len(workflow_matches) > 1:
                names = ", ".join(item.qualified_name for item in workflow_matches[:5])
                raise ValueError(f"Object is ambiguous: {term} ({names})") from None
            root = workflow_matches[0]
        if root.object_type not in {ObjectType.WORKFLOW, ObjectType.SCHEDULER}:
            raise ValueError(f"Not a workflow: {term}")
        children: dict[str, list[dict[str, object]]] = defaultdict(list)
        for relation in self._relations:
            if (
                relation.source_object_id in self._by_id
                and relation.target_object_id in self._by_id
                and relation.source_object_id != relation.target_object_id
            ):
                connection_type: RelationType | None = None
                if relation.relation_type == RelationType.READS:
                    connection_type = RelationType.READS
                elif relation.relation_type == RelationType.WRITES:
                    connection_type = RelationType.WRITES
                children[str(relation.source_object_id)].append(
                    {
                        "object": _object_dict(self._by_id[relation.target_object_id]),
                        "relation": {
                            **_relation_dict(relation),
                            **(
                                {
                                    "connection": self._connection_label(
                                        relation.source_object_id,
                                        connection_type,
                                    )
                                }
                                if connection_type is not None
                                else {}
                            ),
                        },
                    }
                )

        def build(parent: UUID, path: set[UUID]) -> list[dict[str, object]]:
            result = []
            for edge in children.get(str(parent), []):
                object_data = cast(Mapping[str, object], edge["object"])
                child_id = UUID(str(object_data["object_id"]))
                node: dict[str, object] = {
                    "object": object_data,
                    "relation": cast(Mapping[str, object], edge["relation"]),
                }
                if child_id not in path:
                    node["children"] = build(child_id, path | {child_id})
                result.append(node)
            return result

        return {
            "workflow": _object_dict(root),
            "children": build(root.object_id, {root.object_id}),
        }

    def path(self, source: str, target: str) -> dict[str, object]:
        start = self.resolve(source)
        finish = self.resolve(target)
        queue: deque[UUID] = deque([start.object_id])
        previous: dict[UUID, tuple[UUID, Relation]] = {}
        seen = {start.object_id}
        while queue:
            current = queue.popleft()
            if current == finish.object_id:
                break
            for relation in self._outgoing.get(current, []) + self._incoming.get(
                current, []
            ):
                next_id = (
                    relation.target_object_id
                    if relation.source_object_id == current
                    else relation.source_object_id
                )
                if next_id not in seen:
                    seen.add(next_id)
                    previous[next_id] = (current, relation)
                    queue.append(next_id)
        if finish.object_id not in seen:
            raise ValueError(f"No relationship path found: {source} -> {target}")
        ids = [finish.object_id]
        relations: list[Relation] = []
        while ids[-1] != start.object_id:
            parent, relation = previous[ids[-1]]
            ids.append(parent)
            relations.append(relation)
        ids.reverse()
        relations.reverse()
        return {
            "objects": [_object_dict(self._by_id[item_id]) for item_id in ids],
            "relations": [_relation_dict(item) for item in relations],
        }


def tree_lines(result: Mapping[str, object]) -> list[str]:
    """Render query results without conflating containment and execution flow.

    A workflow is a graph, not a tree: one task can have several successors and
    several branches can converge on one task.  Containment, task ordering,
    mapping execution, and data access are therefore rendered separately.
    """

    if "objects" in result:
        objects = cast(Sequence[Mapping[str, object]], result["objects"])
        return [str(item["qualified_name"]) for item in objects]
    if "workflow" in result:
        root = cast(Mapping[str, object], result["workflow"])
        lines = ["Workflow structure:", str(root["qualified_name"])]
        flow: list[tuple[str, str, str]] = []
        executions: list[tuple[str, str, str]] = []
        mapping_tasks: dict[str, list[str]] = defaultdict(list)
        data_relations: list[tuple[str, str, str, str | None, str, int]] = []
        command_details: dict[str, list[str]] = defaultdict(list)
        seen_relations: set[tuple[str, str, str, str | None]] = set()
        task_order: dict[str, int] = {}
        sequence = 0

        # A session-to-mapping edge can be emitted without the connection
        # metadata that lives on the session's Source/Target Definition child.
        # Keep that direction-specific information available while rendering
        # the workflow, so READS and WRITES never inherit the wrong connection.
        session_connections: dict[tuple[str, str], set[str]] = defaultdict(set)
        for node in _iter_workflow_nodes(result.get("children")):
            session = node.get("object")
            if not isinstance(session, Mapping):
                continue
            if session.get("object_type") != ObjectType.SESSION.value:
                continue
            session_name = str(session.get("qualified_name", ""))
            for child_node in _iter_workflow_nodes(node.get("children")):
                child = child_node.get("object")
                relation = child_node.get("relation")
                if not isinstance(child, Mapping) or not isinstance(relation, Mapping):
                    continue
                if relation.get("relation_type") != "BELONGS_TO":
                    continue
                connection = child.get("properties", {})
                if not isinstance(connection, Mapping):
                    continue
                connection_name = connection.get("connectionreference.connectionname")
                if not connection_name:
                    continue
                child_type = child.get("object_type")
                direction = (
                    "READS"
                    if child_type == ObjectType.SOURCE_DEFINITION.value
                    else (
                        "WRITES"
                        if child_type == ObjectType.TARGET_DEFINITION.value
                        else None
                    )
                )
                if direction:
                    session_connections[(session_name, direction)].add(
                        str(connection_name)
                    )

        def collect_edges(
            nodes: object, parent_name: str, task_name: str | None = None
        ) -> None:
            nonlocal sequence
            if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
                return
            for node in nodes:
                if not isinstance(node, Mapping):
                    continue
                item = node.get("object")
                relation = node.get("relation")
                if not isinstance(item, Mapping) or not isinstance(relation, Mapping):
                    continue
                child_name = str(item.get("qualified_name", ""))
                relation_name = str(relation.get("relation_type", ""))
                connection = relation.get("connection")
                connection_name = str(connection) if connection else None
                if not connection_name:
                    candidates = session_connections.get(
                        (parent_name, relation_name), set()
                    )
                    if not candidates and task_name is not None:
                        candidates = session_connections.get(
                            (task_name, relation_name), set()
                        )
                    if len(candidates) == 1:
                        connection_name = next(iter(candidates))
                child_type = str(item.get("object_type", ""))
                if (
                    task_name is not None
                    and child_type == ObjectType.FILE.value
                    and relation_name == "BELONGS_TO"
                ):
                    properties = item.get("properties", {})
                    if isinstance(properties, Mapping):
                        command = properties.get("value")
                        if command:
                            command_details[task_name].append(str(command))
                current_task = (
                    child_name
                    if child_type
                    in {ObjectType.SESSION.value, ObjectType.COMMAND.value}
                    else task_name
                )
                if child_type == ObjectType.COMMAND.value:
                    properties = item.get("properties", {})
                    if isinstance(properties, Mapping):
                        command = properties.get("valuepair.value")
                        if command:
                            command_details[child_name].append(str(command))
                if current_task is not None and current_task not in task_order:
                    task_order[current_task] = len(task_order)
                edge = (parent_name, child_name, relation_name, connection_name)
                if relation_name and edge not in seen_relations:
                    seen_relations.add(edge)
                    if relation_name == "PRECEDES":
                        flow.append((parent_name, child_name, relation_name))
                    elif relation_name == "EXECUTES":
                        executions.append((parent_name, child_name, relation_name))
                        if child_type == ObjectType.MAPPING.value:
                            mapping_tasks[child_name].append(parent_name)
                    elif relation_name == "BELONGS_TO":
                        # Containment is already rendered in the component tree.
                        pass
                    else:
                        data_relations.append(
                            (
                                parent_name,
                                child_name,
                                relation_name,
                                connection_name,
                                current_task or "",
                                sequence,
                            )
                        )
                        sequence += 1
                collect_edges(node.get("children"), child_name, current_task)

        def render(nodes: object, prefix: str = "") -> None:
            if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
                return
            valid_nodes = [node for node in nodes if isinstance(node, Mapping)]
            structure_nodes = []
            for node in valid_nodes:
                relation = node.get("relation")
                relation_name = ""
                if isinstance(relation, Mapping):
                    relation_name = str(relation.get("relation_type", ""))
                item = node.get("object")
                if not isinstance(item, Mapping):
                    continue
                child_name = str(item.get("qualified_name", ""))
                if relation_name == "BELONGS_TO":
                    structure_nodes.append((node, child_name))

            for index, (node, child_name) in enumerate(structure_nodes):
                if not isinstance(node, Mapping):
                    continue
                item = node.get("object")
                if not isinstance(item, Mapping):
                    continue
                branch = "└─ " if index == len(structure_nodes) - 1 else "├─ "
                lines.append(prefix + branch + child_name)
                render(
                    node.get("children"),
                    prefix + ("   " if index == len(structure_nodes) - 1 else "│  "),
                )

        render(result.get("children"))
        collect_edges(result.get("children"), str(root["qualified_name"]))

        # VALUEPAIR entries are persisted as FILE children. Rebuild command
        # details from the graph so all commands remain visible when a task
        # is reached through more than one workflow branch.
        command_details.clear()
        for node in _iter_workflow_nodes(result.get("children")):
            command = node.get("object")
            if not isinstance(command, Mapping):
                continue
            if command.get("object_type") != ObjectType.COMMAND.value:
                continue
            command_name = str(command.get("qualified_name", ""))
            values: list[tuple[int, str]] = []
            for child_node in _iter_workflow_nodes(node.get("children")):
                child = child_node.get("object")
                if not isinstance(child, Mapping):
                    continue
                if child.get("object_type") != ObjectType.FILE.value:
                    continue
                properties = child.get("properties", {})
                if not isinstance(properties, Mapping):
                    continue
                value = properties.get("value")
                if not value:
                    continue
                try:
                    order = int(str(properties.get("execorder", "0")))
                except ValueError:
                    order = 0
                values.append((order, str(value)))
            if not values:
                properties = command.get("properties", {})
                if isinstance(properties, Mapping):
                    value = properties.get("valuepair.value")
                    if value:
                        values.append((0, str(value)))
            for _, value in sorted(set(values), key=lambda item: (item[0], item[1])):
                if value not in command_details[command_name]:
                    command_details[command_name].append(value)

        # A workflow may contain parallel branches that are not connected by a
        # PRECEDES edge.  Rank connected tasks by the longest PRECEDES path so
        # terminal tasks (for example a final parameter-file procedure) are
        # rendered after their predecessors without globally sorting by name.
        flow_rank: dict[str, int] = {}
        for _ in range(len(flow) + 1):
            changed = False
            for source, target, _ in flow:
                candidate = flow_rank.get(source, 0) + 1
                if candidate > flow_rank.get(target, 0):
                    flow_rank[target] = candidate
                    changed = True
            if not changed:
                break

        # Keep the workflow's task order.  Only reorder data edges within the
        # same task so READS describe the input side before WRITES describe the
        # output side.  A global READS/WRITES sort would scramble the flow.
        data_relations.sort(
            key=lambda edge: (
                flow_rank.get(edge[4], 0),
                task_order.get(edge[4], len(task_order)),
                {"READS": 0, "WRITES": 1}.get(edge[2], 2),
                edge[5],
            )
        )
        if flow:
            lines.extend(["", "Task flow (parallel branches and convergence):"])
            for source, target, _ in flow:
                lines.append(f"- {source} --[PRECEDES]--> {target}")
        if executions:
            lines.extend(["", "Task mapping execution:"])
            for source, target, _ in executions:
                lines.append(f"- {source} --[EXECUTES]--> {target}")
        if command_details:
            lines.extend(["", "Command execution details:"])
            for command, commands in command_details.items():
                lines.append(f"- {command}")
                for index, command_text in enumerate(commands, 1):
                    lines.append(f"  {index}. {command_text}")
        if data_relations:
            lines.extend(["", "Workflow and data relationships:"])
            for source, target, relation_name, connection, _, _ in data_relations:
                suffix = f" [DB Connection: {connection}]" if connection else ""
                destination_found = False
                target_details = next(
                    (
                        node.get("object")
                        for node in _iter_workflow_nodes(result.get("children"))
                        if isinstance(node.get("object"), Mapping)
                        and cast(Mapping[str, object], node["object"]).get(
                            "qualified_name"
                        )
                        == target
                    ),
                    None,
                )
                if isinstance(target_details, Mapping):
                    properties = target_details.get("properties", {})
                    if isinstance(properties, Mapping):
                        directory = properties.get("file_writer.output_file_directory")
                        filename = properties.get("file_writer.output_filename")
                        merge_directory = properties.get(
                            "file_writer.merge_file_directory"
                        )
                        merge_name = properties.get("file_writer.merge_file_name")
                        if directory and filename:
                            destination = f"{directory}{filename}"
                            suffix += f" [File: {destination}]"
                            destination_found = True
                        if merge_directory and merge_name:
                            suffix += f" [Merge File: {merge_directory}{merge_name}]"
                            destination_found = True
                if not destination_found:
                    target_leaf = f"::{target.rsplit('::', 1)[-1]}"
                    target_details = next(
                        (
                            node.get("object")
                            for node in _iter_workflow_nodes(result.get("children"))
                            if isinstance(node.get("object"), Mapping)
                            and str(
                                cast(Mapping[str, object], node["object"]).get(
                                    "qualified_name", ""
                                )
                            ).endswith(target_leaf)
                            and str(
                                cast(Mapping[str, object], node["object"]).get(
                                    "object_type", ""
                                )
                            )
                            == ObjectType.TARGET_DEFINITION.value
                            and isinstance(
                                cast(Mapping[str, object], node["object"]).get(
                                    "properties"
                                ),
                                Mapping,
                            )
                            and cast(
                                Mapping[str, object],
                                cast(Mapping[str, object], node["object"]).get(
                                    "properties", {}
                                ),
                            ).get("file_writer.output_file_directory")
                        ),
                        None,
                    )
                    if isinstance(target_details, Mapping):
                        properties = target_details.get("properties", {})
                        if isinstance(properties, Mapping):
                            directory = properties.get(
                                "file_writer.output_file_directory"
                            )
                            filename = properties.get("file_writer.output_filename")
                            merge_directory = properties.get(
                                "file_writer.merge_file_directory"
                            )
                            merge_name = properties.get("file_writer.merge_file_name")
                            if directory and filename:
                                suffix += f" [File: {directory}{filename}]"
                            if merge_directory and merge_name:
                                suffix += (
                                    f" [Merge File: {merge_directory}{merge_name}]"
                                )
                task_sources = mapping_tasks.get(source)
                display_source = task_sources[0] if task_sources else source
                lines.append(
                    f"- {display_source} --[{relation_name}]--> {target}{suffix}"
                )
        return lines

    return [str(result)]


def _iter_workflow_nodes(nodes: object) -> Iterator[Mapping[str, object]]:
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        return
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        typed_node = cast(Mapping[str, object], node)
        yield typed_node
        yield from _iter_workflow_nodes(typed_node.get("children"))
