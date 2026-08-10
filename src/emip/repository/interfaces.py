"""Repository contracts used by the application and future adapters."""

from abc import ABC, abstractmethod
from typing import Any


class MetadataRepository(ABC):
    """Abstract persistence boundary for metadata objects and relations."""

    @abstractmethod
    def save_object(self, metadata_object: Any) -> None:
        """Persist a new metadata object."""

    @abstractmethod
    def update_object(self, metadata_object: Any) -> None:
        """Update an existing metadata object."""

    @abstractmethod
    def delete_object(self, object_id: str) -> None:
        """Delete a metadata object by identifier."""

    @abstractmethod
    def save_relation(self, relation: Any) -> None:
        """Persist a relation between metadata objects."""

    @abstractmethod
    def find_object(self, object_id: str) -> Any | None:
        """Find one metadata object by identifier."""

    @abstractmethod
    def find_upstream(self, object_id: str) -> list[Any]:
        """Find objects upstream of the given object."""

    @abstractmethod
    def find_downstream(self, object_id: str) -> list[Any]:
        """Find objects downstream of the given object."""
