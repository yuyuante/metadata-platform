"""Extract metadata from Informatica PowerCenter XML exports."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from emip.domain import (
    Column,
    MetadataObject,
    ObjectProperty,
    ObjectType,
    ParameterContext,
    ParameterDefinition,
    ParameterResolution,
    ParameterResolutionStatus,
    RelationCandidate,
    RelationType,
)
from emip.parser.embedded_sql import (
    EmbeddedSqlAnalysis,
    EmbeddedSqlAnalyzer,
    InformaticaEmbeddedSqlExtractor,
)
from emip.parser.informatica.parameters import (
    InformaticaParameterResolver,
    ParameterDiagnostic,
    ParameterFileCache,
)


class InformaticaMetadataParser:
    """Parse deterministic PowerCenter repository metadata and workflow links."""

    system_name = "INFORMATICA"
    source_type = "STATIC_INFORMATICA_XML"

    def __init__(self, profiler: Any | None = None) -> None:
        self._profiler = profiler
        self._embedded_sql_extractor = InformaticaEmbeddedSqlExtractor()
        self._embedded_sql_analyzer = EmbeddedSqlAnalyzer()
        self._parameter_files = ParameterFileCache()
        self._source_path = Path(".")

    def parse(self, path: Path) -> list[MetadataObject]:
        self._source_path = path
        started_at = perf_counter()
        reading_started_at = perf_counter()
        xml_text = _read_xml(path)
        if self._profiler is not None:
            self._profiler.record("File reading", perf_counter() - reading_started_at)
        parsing_started_at = perf_counter()
        root = ET.fromstring(xml_text)
        if self._profiler is not None:
            self._profiler.record("XML parsing", perf_counter() - parsing_started_at)
        if _name(root) != "POWERMART":
            raise ValueError("Unsupported XML root; expected POWERMART")
        objects: list[MetadataObject] = []
        for folder in (
            element for element in root.iter() if _name(element) == "FOLDER"
        ):
            objects.extend(self._folder(folder))
        if self._profiler is not None:
            self._profiler.record("Namespace processing", 0.0)
            self._profiler.record(
                "Workflow extraction",
                0.0,
                sum(item.object_type.value == "WORKFLOW" for item in objects),
            )
            self._profiler.record(
                "Task extraction",
                0.0,
                sum(
                    item.object_type.value
                    in {
                        "COMMAND",
                        "SESSION",
                        "DECISION",
                        "EVENT_WAIT",
                        "WORKLET",
                        "EMAIL",
                        "TIMER",
                        "START_TASK",
                    }
                    for item in objects
                ),
            )
            self._profiler.record(
                "Session extraction",
                0.0,
                sum(item.object_type.value == "SESSION" for item in objects),
            )
            self._profiler.record(
                "Mapping extraction",
                0.0,
                sum(item.object_type.value == "MAPPING" for item in objects),
            )
            self._profiler.record(
                "Transformation extraction",
                0.0,
                sum(
                    item.object_type.value
                    in {"SOURCE_QUALIFIER", "LOOKUP", "UPDATE_STRATEGY"}
                    for item in objects
                ),
            )
            relation_count = sum(len(item.relation_candidates) for item in objects)
            self._profiler.record(
                "Relation extraction", perf_counter() - started_at, relation_count
            )
            self._profiler.record("Relation generation", 0.0, relation_count)
            self._profiler.count("MetadataObject", len(objects))
            self._profiler.record("MetadataObject creation", 0.0, len(objects))
            self._profiler.count(
                "Relation", sum(len(item.relation_candidates) for item in objects)
            )
            for object_type in {"WORKFLOW", "TASK", "SESSION", "MAPPING"}:
                self._profiler.count(
                    object_type.title(),
                    sum(item.object_type.value == object_type for item in objects),
                )
            self._profiler.count(
                "Transformation",
                sum(
                    item.object_type.value
                    in {"SOURCE_QUALIFIER", "LOOKUP", "UPDATE_STRATEGY"}
                    for item in objects
                ),
            )
        return objects

    def _folder(self, folder: ET.Element) -> list[MetadataObject]:
        folder_name = _attr(folder, "NAME", "UNKNOWN_FOLDER")
        folder_qn = self._qn(folder_name)
        result: list[MetadataObject] = []
        for config in _children(folder, "CONFIG"):
            result.append(
                self._object(ObjectType.SESSION_CONFIG, folder_qn, config, "NAME")
            )
        for source in _children(folder, "SOURCE"):
            result.append(
                self._definition(folder_qn, source, ObjectType.SOURCE_DEFINITION)
            )
        for target in _children(folder, "TARGET"):
            result.append(
                self._definition(folder_qn, target, ObjectType.TARGET_DEFINITION)
            )
        mappings = {
            _attr(item, "NAME", ""): item for item in _children(folder, "MAPPING")
        }
        sessions = {
            _attr(item, "NAME", ""): item
            for item in folder.iter()
            if _name(item) == "SESSION" and _attr(item, "NAME", "")
        }
        task_definitions = {
            _attr(item, "NAME", ""): item
            for item in folder.iter()
            if _name(item) == "TASK" and _attr(item, "NAME", "")
        }
        mapping_aliases = {
            _attr(item, "NAME", ""): self._qn(
                _attr(item, "FOLDERNAME", folder_qn),
                _attr(item, "REFOBJECTNAME", ""),
            )
            for item in folder.iter()
            if _name(item) == "SHORTCUT"
            and _attr(item, "NAME", "")
            and _attr(item, "REFOBJECTNAME", "")
        }
        for mapping in mappings.values():
            result.extend(self._mapping(folder_qn, mapping))
        for workflow in _children(folder, "WORKFLOW"):
            result.extend(
                self._workflow(
                    folder_qn,
                    workflow,
                    mappings,
                    sessions,
                    mapping_aliases,
                    task_definitions,
                )
            )
        return result

    def _workflow(
        self,
        folder_qn: str,
        workflow: ET.Element,
        mappings: dict[str, ET.Element],
        sessions: dict[str, ET.Element],
        mapping_aliases: dict[str, str],
        task_definitions: dict[str, ET.Element],
    ) -> list[MetadataObject]:
        name = _attr(workflow, "NAME", "UNKNOWN_WORKFLOW")
        workflow_qn = self._qn(folder_qn, name)
        parameter_references = _parameter_file_references(workflow)
        result = [self._object(ObjectType.WORKFLOW, workflow_qn, workflow, "NAME")]
        for child in list(workflow):
            tag = _name(child)
            if tag == "SCHEDULER":
                scheduler = self._object(
                    ObjectType.SCHEDULER, workflow_qn, child, "NAME"
                )
                result.append(scheduler)
                if scheduler.qualified_name != workflow_qn:
                    result[0].relation_candidates += (
                        self._relation(
                            workflow_qn,
                            scheduler.qualified_name,
                            RelationType.BELONGS_TO,
                            child,
                        ),
                    )
            elif tag in {"TASK", "SESSION"}:
                result.extend(
                    self._task(
                        workflow_qn,
                        folder_qn,
                        child,
                        mappings,
                        mapping_aliases,
                        parameter_references,
                    )
                )
            elif tag == "WORKFLOWVARIABLE":
                result.append(
                    self._child(workflow_qn, child, ObjectType.WORKFLOW_VARIABLE)
                )
            elif tag == "ATTRIBUTE":
                result.append(
                    self._child(workflow_qn, child, ObjectType.WORKFLOW_ATTRIBUTE)
                )
        by_qn = {item.qualified_name: item for item in result}
        for task_instance in _children(workflow, "TASKINSTANCE"):
            instance_objects = self._task_instance(
                workflow_qn,
                folder_qn,
                task_instance,
                mappings,
                sessions,
                mapping_aliases,
                task_definitions,
                parameter_references,
            )
            for item in instance_objects:
                if item.qualified_name not in by_qn:
                    result.append(item)
                    by_qn[item.qualified_name] = item
        for link in _children(workflow, "WORKFLOWLINK"):
            source_name = _attr(link, "FROMTASK", "")
            target_name = _attr(link, "TOTASK", "")
            source_qn = self._qn(workflow_qn, source_name)
            target_qn = self._qn(workflow_qn, target_name)
            if (
                source_name
                and target_name
                and source_qn in by_qn
                and target_qn in by_qn
                and source_qn != target_qn
            ):
                by_qn[source_qn].relation_candidates += (
                    self._relation(source_qn, target_qn, RelationType.PRECEDES, link),
                )
        return result

    def _task_instance(
        self,
        workflow_qn: str,
        folder_qn: str,
        task_instance: ET.Element,
        mappings: dict[str, ET.Element],
        sessions: dict[str, ET.Element],
        mapping_aliases: dict[str, str],
        task_definitions: dict[str, ET.Element],
        workflow_parameter_references: tuple[str, ...],
    ) -> list[MetadataObject]:
        """Materialize workflow nodes represented only by TASKINSTANCE elements."""
        name = _attr(
            task_instance,
            "NAME",
            _attr(task_instance, "TASKNAME", "UNKNOWN_TASK"),
        )
        raw_type = _attr(task_instance, "TASKTYPE", "WORKLET").upper().replace(" ", "")
        object_type = {
            "COMMAND": ObjectType.COMMAND,
            "DECISION": ObjectType.DECISION,
            "EVENTWAIT": ObjectType.EVENT_WAIT,
            "WORKLET": ObjectType.WORKLET,
            "EMAIL": ObjectType.EMAIL,
            "TIMER": ObjectType.TIMER,
            "START": ObjectType.START_TASK,
            "SESSION": ObjectType.SESSION,
            "ASSIGNMENT": ObjectType.WORKLET,
        }.get(raw_type, ObjectType.WORKLET)
        task_qn = self._qn(workflow_qn, name)
        definition = task_definitions.get(_attr(task_instance, "TASKNAME", name))
        if definition is None:
            # Command tasks can be represented by a reusable session
            # TASKINSTANCE whose TASKNAME points at the session component,
            # while the TASKINSTANCE NAME points at the actual Command task.
            # Prefer the named task definition when the session name has no
            # matching definition.
            definition = task_definitions.get(name)
        if (
            definition is not None
            and _attr(definition, "TYPE", "").upper() == "COMMAND"
        ):
            object_type = ObjectType.COMMAND
        item = self._object(object_type, task_qn, definition or task_instance, "NAME")
        item.relation_candidates += (
            self._relation(
                workflow_qn, task_qn, RelationType.BELONGS_TO, task_instance
            ),
        )
        result = [item]
        if object_type == ObjectType.SESSION:
            session_definition = sessions.get(_attr(task_instance, "TASKNAME", name))
            mapping_name = (
                _attr(session_definition, "MAPPINGNAME", "")
                if session_definition is not None
                else ""
            )
            mapping_target = mapping_aliases.get(mapping_name)
            if mapping_target is None and mapping_name in mappings:
                mapping_target = self._qn(folder_qn, mapping_name)
            if mapping_target:
                item.relation_candidates += (
                    self._relation(
                        task_qn,
                        mapping_target,
                        RelationType.EXECUTES,
                        task_instance,
                    ),
                )
            # A reusable session's TASKINSTANCE usually contains only the
            # workflow placement.  Its transformations and connection
            # references live on the reusable SESSION definition, so
            # materialize those children under the workflow task as well.
            if session_definition is not None:
                result.extend(
                    self._session_children(
                        task_qn,
                        session_definition,
                        item,
                        mapping_name,
                        workflow_parameter_references,
                    )
                )
        if object_type == ObjectType.COMMAND and definition is not None:
            for command in _children(definition, "VALUEPAIR"):
                child = self._child(task_qn, command, ObjectType.FILE, "NAME")
                item.relation_candidates += (
                    self._relation(
                        task_qn, child.qualified_name, RelationType.BELONGS_TO, command
                    ),
                )
                result.append(child)
        return result

    def _task(
        self,
        workflow_qn: str,
        folder_qn: str,
        task: ET.Element,
        mappings: dict[str, ET.Element],
        mapping_aliases: dict[str, str] | None = None,
        workflow_parameter_references: tuple[str, ...] = (),
    ) -> list[MetadataObject]:
        name = _attr(task, "NAME", "UNKNOWN_TASK")
        raw_type = (
            _attr(task, "TYPE", "SESSION" if _name(task) == "SESSION" else "WORKLET")
            .upper()
            .replace(" ", "")
        )
        object_type = {
            "COMMAND": ObjectType.COMMAND,
            "DECISION": ObjectType.DECISION,
            "EVENTWAIT": ObjectType.EVENT_WAIT,
            "WORKLET": ObjectType.WORKLET,
            "EMAIL": ObjectType.EMAIL,
            "TIMER": ObjectType.TIMER,
            "START": ObjectType.START_TASK,
            "SESSION": ObjectType.SESSION,
        }.get(raw_type, ObjectType.WORKLET)
        task_qn = self._qn(workflow_qn, name)
        item = self._object(object_type, task_qn, task, "NAME")
        if task_qn != workflow_qn:
            item.relation_candidates += (
                self._relation(workflow_qn, task_qn, RelationType.BELONGS_TO, task),
            )
        result = [item]
        if object_type == ObjectType.SESSION:
            mapping_name = _attr(task, "MAPPINGNAME", "")
            mapping_target = (mapping_aliases or {}).get(mapping_name)
            if mapping_target is None and mapping_name in mappings:
                mapping_target = self._qn(folder_qn, mapping_name)
            if mapping_target:
                item.relation_candidates += (
                    self._relation(
                        task_qn,
                        mapping_target,
                        RelationType.EXECUTES,
                        task,
                    ),
                )
            result.extend(
                self._session_children(
                    task_qn,
                    task,
                    item,
                    mapping_name,
                    workflow_parameter_references,
                )
            )
        elif object_type == ObjectType.COMMAND:
            for command in _children(task, "VALUEPAIR"):
                child = self._child(task_qn, command, ObjectType.FILE, "NAME")
                item.relation_candidates += (
                    self._relation(
                        task_qn, child.qualified_name, RelationType.BELONGS_TO, command
                    ),
                )
                result.append(child)
        return result

    def _session_children(
        self,
        session_qn: str,
        session: ET.Element,
        session_item: MetadataObject,
        mapping_name: str,
        workflow_parameter_references: tuple[str, ...] = (),
    ) -> list[MetadataObject]:
        result: list[MetadataObject] = []
        parameter_resolver = self._session_parameter_resolver(
            session_qn,
            mapping_name,
            session,
            session_item,
            workflow_parameter_references,
        )
        types = {
            "SOURCE DEFINITION": ObjectType.SOURCE_DEFINITION,
            "TARGET DEFINITION": ObjectType.TARGET_DEFINITION,
            "SOURCE QUALIFIER": ObjectType.SOURCE_QUALIFIER,
            "LOOKUP PROCEDURE": ObjectType.LOOKUP,
            "UPDATE STRATEGY": ObjectType.UPDATE_STRATEGY,
        }
        extensions = _children(session, "SESSIONEXTENSION")
        connection_by_instance: dict[str, str] = {}
        for extension in extensions:
            connection = next(
                (
                    prop.property_value
                    for prop in _properties(extension)
                    if prop.property_name == "connectionreference.connectionname"
                ),
                "",
            )
            instance_name = _attr(extension, "SINSTANCENAME", "")
            if connection and instance_name:
                resolved_connection, _ = _resolve_connection(
                    connection, parameter_resolver
                )
                if resolved_connection:
                    connection_by_instance[instance_name] = resolved_connection

        for transformation in _children(session, "SESSTRANSFORMATIONINST"):
            kind = types.get(_attr(transformation, "TRANSFORMATIONTYPE", "").upper())
            if kind is not None:
                child = self._child(
                    session_qn,
                    transformation,
                    kind,
                    "SINSTANCENAME",
                    analyze_embedded_sql=False,
                )
                raw_connection = _raw_connection(transformation, extensions)
                connection = connection_by_instance.get(
                    _attr(transformation, "SINSTANCENAME", "")
                )
                if not connection:
                    connection = _source_connection(
                        transformation, extensions, connection_by_instance
                    )
                if connection:
                    child.properties = child.properties + (
                        ObjectProperty(
                            property_name="connectionreference.connectionname",
                            property_value=connection,
                        ),
                    )
                connection_resolution: ParameterResolution | None = None
                if raw_connection:
                    _, connection_resolution = _resolve_connection(
                        raw_connection, parameter_resolver
                    )
                self._attach_embedded_sql(
                    child,
                    transformation,
                    connection or None,
                    parameter_resolver,
                    connection_resolution,
                )
                if kind is ObjectType.TARGET_DEFINITION:
                    writer_properties: list[ObjectProperty] = []
                    for extension in extensions:
                        if (
                            _attr(extension, "SINSTANCENAME", "")
                            != _attr(transformation, "SINSTANCENAME", "")
                            or "writer" not in _attr(extension, "NAME", "").lower()
                        ):
                            continue
                        for attribute in _children(extension, "ATTRIBUTE"):
                            attribute_name = _attr(attribute, "NAME", "").strip()
                            attribute_value = _attr(attribute, "VALUE", "")
                            if attribute_name:
                                property_name = "_".join(attribute_name.lower().split())
                                writer_properties.append(
                                    ObjectProperty(
                                        property_name=f"file_writer.{property_name}",
                                        property_value=attribute_value,
                                    )
                                )
                    child.properties = child.properties + tuple(writer_properties)
                result.append(child)
                session_item.relation_candidates += (
                    self._relation(
                        session_qn,
                        child.qualified_name,
                        RelationType.BELONGS_TO,
                        transformation,
                    ),
                )
            for partition in _children(transformation, "PARTITION"):
                child = self._child(session_qn, partition, ObjectType.PARTITION)
                result.append(child)
                session_item.relation_candidates += (
                    self._relation(
                        session_qn,
                        child.qualified_name,
                        RelationType.BELONGS_TO,
                        partition,
                    ),
                )
        for extension in extensions:
            child = self._child(session_qn, extension, ObjectType.CONNECTION)
            result.append(child)
            session_item.relation_candidates += (
                self._relation(
                    session_qn,
                    child.qualified_name,
                    RelationType.BELONGS_TO,
                    extension,
                ),
            )
        return result

    def _session_parameter_resolver(
        self,
        session_qn: str,
        mapping_name: str,
        session: ET.Element,
        session_item: MetadataObject,
        workflow_parameter_references: tuple[str, ...] = (),
    ) -> InformaticaParameterResolver:
        """Create a resolver from only the session's explicit file reference."""

        parts = session_qn.split("::")
        context = ParameterContext(
            folder=parts[-3] if len(parts) >= 3 else "",
            workflow=parts[-2] if len(parts) >= 2 else "",
            session=parts[-1],
            mapping=mapping_name or None,
        )
        session_references = _parameter_file_references(session)
        references = session_references or workflow_parameter_references
        diagnostics: list[ParameterDiagnostic] = []
        definitions: tuple[ParameterDefinition, ...] = ()
        unresolved_status = ParameterResolutionStatus.UNRESOLVED
        if len(references) == 1:
            parsed, diagnostic = self._parameter_files.load_reference(
                references[0], self._source_path
            )
            if parsed is not None:
                definitions = parsed.definitions
                diagnostics.extend(parsed.diagnostics)
            if diagnostic is not None:
                diagnostics.append(diagnostic)
            session_item.properties += (
                ObjectProperty(
                    property_name="parameter_file.reference",
                    property_value=references[0],
                ),
            )
        elif len(references) > 1:
            unresolved_status = ParameterResolutionStatus.AMBIGUOUS
            diagnostics.append(
                ParameterDiagnostic(
                    str(self._source_path),
                    None,
                    "multiple parameter file references are ambiguous",
                )
            )
        session_item.properties += tuple(
            ObjectProperty(
                property_name="parameter.diagnostic",
                property_value=(
                    f"{diagnostic.source_file}:"
                    f"{diagnostic.line_number or '-'}: {diagnostic.message}"
                ),
            )
            for diagnostic in diagnostics
        )
        return InformaticaParameterResolver(
            context,
            definitions,
            tuple(diagnostics),
            unresolved_status,
        )

    def _mapping(self, folder_qn: str, mapping: ET.Element) -> list[MetadataObject]:
        item = self._object(
            ObjectType.MAPPING,
            self._qn(folder_qn, _attr(mapping, "NAME", "UNKNOWN_MAPPING")),
            mapping,
            "NAME",
        )
        result = [item]
        for instance in _children(mapping, "INSTANCE"):
            instance_type = _attr(instance, "TYPE", "").upper()
            definition_name = _attr(instance, "TRANSFORMATION_NAME", "")
            if instance_type == "SOURCE" and definition_name:
                item.relation_candidates += (
                    self._relation(
                        item.qualified_name,
                        self._qn(folder_qn, definition_name),
                        RelationType.READS,
                        instance,
                    ),
                )
            elif instance_type == "TARGET" and definition_name:
                item.relation_candidates += (
                    self._relation(
                        item.qualified_name,
                        self._qn(folder_qn, definition_name),
                        RelationType.WRITES,
                        instance,
                    ),
                )
        for transformation in _children(mapping, "TRANSFORMATION"):
            kind = {
                "SOURCE QUALIFIER": ObjectType.SOURCE_QUALIFIER,
                "LOOKUP PROCEDURE": ObjectType.LOOKUP,
                "UPDATE STRATEGY": ObjectType.UPDATE_STRATEGY,
            }.get(_attr(transformation, "TYPE", "").upper())
            if kind is not None:
                result.append(self._child(item.qualified_name, transformation, kind))
        return result

    def _definition(
        self, folder_qn: str, element: ET.Element, kind: ObjectType
    ) -> MetadataObject:
        item = self._object(
            kind,
            self._qn(folder_qn, _attr(element, "NAME", "UNKNOWN_DEFINITION")),
            element,
            "NAME",
        )
        fields = [
            child
            for child in list(element)
            if _name(child) in {"SOURCEFIELD", "TARGETFIELD"}
        ]
        item.columns = tuple(
            Column(
                column_name=_attr(field, "NAME", ""),
                ordinal_position=index,
                datatype=_attr(field, "DATATYPE", ""),
            )
            for index, field in enumerate(fields, 1)
            if _attr(field, "NAME", "")
        )
        return item

    def _child(
        self,
        parent_qn: str,
        element: ET.Element,
        kind: ObjectType,
        name_attribute: str = "NAME",
        *,
        analyze_embedded_sql: bool = True,
    ) -> MetadataObject:
        return self._object(
            kind,
            self._qn(parent_qn, _attr(element, name_attribute, _name(element))),
            element,
            name_attribute,
            analyze_embedded_sql=analyze_embedded_sql,
        )

    def _object(
        self,
        kind: ObjectType,
        qualified_name: str,
        element: ET.Element,
        name_attribute: str,
        *,
        analyze_embedded_sql: bool = True,
    ) -> MetadataObject:
        name = _attr(element, name_attribute, _attr(element, "NAME", _name(element)))
        item = MetadataObject.create(
            kind,
            self.system_name,
            qualified_name,
            name,
            description=_attr(element, "DESCRIPTION", "") or None,
            properties=_properties(element),
        )
        if analyze_embedded_sql:
            self._attach_embedded_sql(item, element)
        return item

    def _attach_embedded_sql(
        self,
        item: MetadataObject,
        element: ET.Element,
        connection_name: str | None = None,
        parameter_resolver: InformaticaParameterResolver | None = None,
        connection_resolution: ParameterResolution | None = None,
    ) -> None:
        """Retain SQL evidence and attach safe relation candidates in one pass."""

        fragments = self._embedded_sql_extractor.extract(
            item.qualified_name,
            item.object_type,
            element,
            self._source_path,
            connection_name,
        )
        for index, fragment in enumerate(fragments, 1):
            resolutions: tuple[ParameterResolution, ...] = ()
            if parameter_resolver is not None:
                substitution = parameter_resolver.substitute_sql(fragment.raw_sql)
                resolutions = tuple(dict.fromkeys(substitution.resolutions))
                if connection_resolution is not None:
                    resolutions = tuple(
                        dict.fromkeys(resolutions + (connection_resolution,))
                    )
                fragment = replace(
                    fragment,
                    resolved_sql=(
                        substitution.resolved_sql
                        if substitution.resolved_sql != fragment.raw_sql
                        else None
                    ),
                    parameter_resolutions=resolutions,
                )
            analysis = self._embedded_sql_analyzer.analyze(fragment)
            item.properties += _embedded_sql_properties(index, analysis)
            item.relation_candidates = tuple(
                dict.fromkeys(item.relation_candidates + analysis.relations)
            )

    def _relation(
        self, source: str, target: str, kind: RelationType, evidence: ET.Element
    ) -> RelationCandidate:
        return RelationCandidate(
            source,
            target,
            kind,
            self.source_type,
            ET.tostring(evidence, encoding="unicode"),
        )

    @staticmethod
    def _qn(*parts: str) -> str:
        return "::".join(part for part in parts if part)


def _read_xml(path: Path) -> str:
    data = path.read_bytes()
    match = re.search(rb"encoding=['\"]([^'\"]+)['\"]", data[:256], re.I)
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    return data.decode(encoding)


def _parameter_file_references(element: ET.Element) -> tuple[str, ...]:
    """Return distinct literal parameter-file references on one XML scope."""

    return tuple(
        dict.fromkeys(
            _attr(attribute, "VALUE", "").strip()
            for attribute in _children(element, "ATTRIBUTE")
            if " ".join(_attr(attribute, "NAME", "").casefold().split())
            == "parameter filename"
            and _attr(attribute, "VALUE", "").strip()
        )
    )


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _name(child) == name]


def _attr(element: ET.Element, name: str, default: str) -> str:
    return element.attrib.get(name, default)


def _source_connection(
    transformation: ET.Element,
    extensions: list[ET.Element],
    connection_by_instance: dict[str, str],
) -> str:
    """Resolve a source definition through its source-qualifier reader extension."""

    instance_name = _attr(transformation, "SINSTANCENAME", "")
    for extension in extensions:
        if _attr(extension, "SINSTANCENAME", "") != instance_name:
            continue
        source_qualifier = _attr(extension, "DSQINSTNAME", "")
        return connection_by_instance.get(source_qualifier, "")
    return ""


def _raw_connection(transformation: ET.Element, extensions: list[ET.Element]) -> str:
    """Return the role-specific connection reference before parameter resolution."""

    instance_name = _attr(transformation, "SINSTANCENAME", "")
    extension_by_instance = {
        _attr(extension, "SINSTANCENAME", ""): extension for extension in extensions
    }
    extension = extension_by_instance.get(instance_name)
    if extension is None:
        return ""
    connection = next(
        (
            prop.property_value or ""
            for prop in _properties(extension)
            if prop.property_name == "connectionreference.connectionname"
        ),
        "",
    )
    if connection:
        return connection
    source_qualifier = _attr(extension, "DSQINSTNAME", "")
    qualifier_extension = extension_by_instance.get(source_qualifier)
    if qualifier_extension is None:
        return ""
    return next(
        (
            prop.property_value or ""
            for prop in _properties(qualifier_extension)
            if prop.property_name == "connectionreference.connectionname"
        ),
        "",
    )


def _resolve_connection(
    connection: str, resolver: InformaticaParameterResolver
) -> tuple[str | None, ParameterResolution | None]:
    """Resolve a connection token exactly or withhold provider context."""

    if not connection.startswith("$$"):
        return connection, None
    resolution = resolver.resolve(connection)
    if (
        resolution.status is ParameterResolutionStatus.EXACT
        and resolution.value is not None
    ):
        return resolution.value, resolution
    return None, resolution


def _properties(element: ET.Element) -> tuple[ObjectProperty, ...]:
    values: list[ObjectProperty] = []
    for key, value in sorted(element.attrib.items()):
        values.append(ObjectProperty(property_name=key.lower(), property_value=value))
    for child in list(element):
        if _name(child) in {
            "ATTRIBUTE",
            "TABLEATTRIBUTE",
            "VALUEPAIR",
            "CONNECTIONREFERENCE",
            "SCHEDULEINFO",
        }:
            for key, value in sorted(child.attrib.items()):
                values.append(
                    ObjectProperty(
                        property_name=f"{_name(child).lower()}.{key.lower()}",
                        property_value=value,
                    )
                )
    return tuple(values)


def _embedded_sql_properties(
    index: int, analysis: EmbeddedSqlAnalysis
) -> tuple[ObjectProperty, ...]:
    """Serialize fragment evidence without requiring relation-schema changes."""

    fragment = analysis.fragment
    prefix = f"embedded_sql.{index}"
    values = [
        ObjectProperty(
            property_name=f"{prefix}.property", property_value=fragment.property_name
        ),
        ObjectProperty(
            property_name=f"{prefix}.role", property_value=fragment.role.value
        ),
        ObjectProperty(
            property_name=f"{prefix}.status", property_value=analysis.status.value
        ),
        ObjectProperty(
            property_name=f"{prefix}.raw_sql", property_value=fragment.raw_sql
        ),
        ObjectProperty(
            property_name=f"{prefix}.source_root", property_value=fragment.source_root
        ),
        ObjectProperty(
            property_name=f"{prefix}.source_file", property_value=fragment.source_file
        ),
        ObjectProperty(
            property_name=f"{prefix}.xml_context", property_value=fragment.xml_context
        ),
    ]
    if fragment.resolved_sql is not None:
        values.append(
            ObjectProperty(
                property_name=f"{prefix}.resolved_sql",
                property_value=fragment.resolved_sql,
            )
        )
    values.extend(
        ObjectProperty(
            property_name=f"{prefix}.parameter_resolution",
            property_value=json.dumps(
                {
                    "token": resolution.token,
                    "value": resolution.value,
                    "status": resolution.status.value,
                    "source_type": (
                        resolution.source_type.value
                        if resolution.source_type is not None
                        else None
                    ),
                    "source_file": resolution.source_file,
                    "source_root": resolution.source_root,
                    "scope": (
                        resolution.scope_type.value
                        if resolution.scope_type is not None
                        else None
                    ),
                    "scope_identity": resolution.scope_identity,
                    "environment": resolution.environment,
                    "precedence": resolution.precedence,
                    "evidence": resolution.evidence,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        for resolution in fragment.parameter_resolutions
    )
    if fragment.connection_name:
        values.append(
            ObjectProperty(
                property_name=f"{prefix}.connection",
                property_value=fragment.connection_name,
            )
        )
    values.extend(
        ObjectProperty(
            property_name=f"{prefix}.unresolved_reference", property_value=value
        )
        for value in analysis.unresolved_references
    )
    values.extend(
        ObjectProperty(property_name=f"{prefix}.error", property_value=value)
        for value in analysis.errors
    )
    return tuple(values)
