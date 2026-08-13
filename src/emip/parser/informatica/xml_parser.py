"""Extract metadata from Informatica PowerCenter XML exports."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from time import perf_counter
from typing import Any

from emip.domain import (
    Column,
    MetadataObject,
    ObjectProperty,
    ObjectType,
    RelationCandidate,
    RelationType,
)


class InformaticaMetadataParser:
    """Parse deterministic PowerCenter repository metadata and workflow links."""

    system_name = "INFORMATICA"
    source_type = "STATIC_INFORMATICA_XML"

    def __init__(self, profiler: Any | None = None) -> None:
        self._profiler = profiler

    def parse(self, path: Path) -> list[MetadataObject]:
        started_at = perf_counter()
        root = ET.fromstring(_read_xml(path))
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
            self._profiler.record(
                "Relation extraction",
                perf_counter() - started_at,
                sum(len(item.relation_candidates) for item in objects),
            )
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
        for mapping in mappings.values():
            result.extend(self._mapping(folder_qn, mapping))
        for workflow in _children(folder, "WORKFLOW"):
            result.extend(self._workflow(folder_qn, workflow, mappings))
        return result

    def _workflow(
        self, folder_qn: str, workflow: ET.Element, mappings: dict[str, ET.Element]
    ) -> list[MetadataObject]:
        name = _attr(workflow, "NAME", "UNKNOWN_WORKFLOW")
        workflow_qn = self._qn(folder_qn, name)
        result = [self._object(ObjectType.WORKFLOW, workflow_qn, workflow, "NAME")]
        for child in list(workflow):
            tag = _name(child)
            if tag == "SCHEDULER":
                scheduler = self._object(
                    ObjectType.SCHEDULER, workflow_qn, child, "NAME"
                )
                result.append(scheduler)
                result[0].relation_candidates += (
                    self._relation(
                        workflow_qn,
                        scheduler.qualified_name,
                        RelationType.BELONGS_TO,
                        child,
                    ),
                )
            elif tag in {"TASK", "SESSION"}:
                result.extend(self._task(workflow_qn, folder_qn, child, mappings))
            elif tag == "WORKFLOWVARIABLE":
                result.append(
                    self._child(workflow_qn, child, ObjectType.WORKFLOW_VARIABLE)
                )
            elif tag == "ATTRIBUTE":
                result.append(
                    self._child(workflow_qn, child, ObjectType.WORKFLOW_ATTRIBUTE)
                )
        by_qn = {item.qualified_name: item for item in result}
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
            ):
                by_qn[source_qn].relation_candidates += (
                    self._relation(source_qn, target_qn, RelationType.EXECUTES, link),
                )
        return result

    def _task(
        self,
        workflow_qn: str,
        folder_qn: str,
        task: ET.Element,
        mappings: dict[str, ET.Element],
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
        item.relation_candidates += (
            self._relation(workflow_qn, task_qn, RelationType.BELONGS_TO, task),
        )
        result = [item]
        if object_type == ObjectType.SESSION:
            mapping_name = _attr(task, "MAPPINGNAME", "")
            if mapping_name in mappings:
                item.relation_candidates += (
                    self._relation(
                        task_qn,
                        self._qn(folder_qn, mapping_name),
                        RelationType.EXECUTES,
                        task,
                    ),
                )
            result.extend(self._session_children(task_qn, task, item))
        elif object_type == ObjectType.COMMAND:
            for command in _children(task, "VALUEPAIR"):
                result.append(self._child(task_qn, command, ObjectType.FILE, "NAME"))
        return result

    def _session_children(
        self,
        session_qn: str,
        session: ET.Element,
        session_item: MetadataObject,
    ) -> list[MetadataObject]:
        result: list[MetadataObject] = []
        types = {
            "SOURCE DEFINITION": ObjectType.SOURCE_DEFINITION,
            "TARGET DEFINITION": ObjectType.TARGET_DEFINITION,
            "SOURCE QUALIFIER": ObjectType.SOURCE_QUALIFIER,
            "LOOKUP PROCEDURE": ObjectType.LOOKUP,
            "UPDATE STRATEGY": ObjectType.UPDATE_STRATEGY,
        }
        for transformation in _children(session, "SESSTRANSFORMATIONINST"):
            kind = types.get(_attr(transformation, "TRANSFORMATIONTYPE", "").upper())
            if kind is not None:
                child = self._child(session_qn, transformation, kind, "SINSTANCENAME")
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
        for extension in _children(session, "SESSIONEXTENSION"):
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
    ) -> MetadataObject:
        return self._object(
            kind,
            self._qn(parent_qn, _attr(element, name_attribute, _name(element))),
            element,
            name_attribute,
        )

    def _object(
        self,
        kind: ObjectType,
        qualified_name: str,
        element: ET.Element,
        name_attribute: str,
    ) -> MetadataObject:
        name = _attr(element, name_attribute, _attr(element, "NAME", _name(element)))
        return MetadataObject.create(
            kind,
            self.system_name,
            qualified_name,
            name,
            description=_attr(element, "DESCRIPTION", "") or None,
            properties=_properties(element),
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


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _name(child) == name]


def _attr(element: ET.Element, name: str, default: str) -> str:
    return element.attrib.get(name, default)


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
