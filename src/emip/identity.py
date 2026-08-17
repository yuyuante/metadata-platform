"""Shared metadata identity normalization helpers."""

from __future__ import annotations


def normalize_identifier(value: str) -> tuple[str, ...]:
    """Return case-insensitive identifier segments without SQL quoting."""

    value = value.replace("::", ".")
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in value.strip():
        if quote is not None:
            if character == quote:
                quote = None
            else:
                current.append(character)
        elif character in {'"', "'", "["}:
            quote = "]" if character == "[" else character
        elif character == ".":
            if current:
                segments.append("".join(current).strip().casefold())
                current = []
        else:
            current.append(character)
    if current:
        segments.append("".join(current).strip().casefold())
    return tuple(segment for segment in segments if segment)


def unquote_identifier(value: str) -> tuple[str, ...]:
    """Return identifier segments with quoting removed and case preserved."""

    value = value.replace("::", ".")
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in value.strip():
        if quote is not None:
            if character == quote:
                quote = None
            else:
                current.append(character)
        elif character in {'"', "'", "["}:
            quote = "]" if character == "[" else character
        elif character == ".":
            if current:
                segments.append("".join(current).strip())
                current = []
        else:
            current.append(character)
    if current:
        segments.append("".join(current).strip())
    return tuple(segment for segment in segments if segment)


def physical_identity_keys(value: str) -> set[tuple[str, ...]]:
    """Build full, schema-qualified, and object-only physical identity keys."""

    parts = normalize_identifier(value)
    if not parts:
        return set()
    keys = {parts, (parts[-1],)}
    if len(parts) >= 2:
        keys.add(parts[-2:])
    return keys


def suffix_identity_keys(
    value: str, removable_prefixes: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    """Build physical keys and optionally remove provider naming prefixes."""

    keys = physical_identity_keys(value)
    parts = normalize_identifier(value)
    if not parts:
        return keys
    terminal = parts[-1]
    changed = True
    while changed:
        changed = False
        for prefix in sorted(removable_prefixes, key=len, reverse=True):
            normalized_prefix = prefix.casefold()
            if terminal.startswith(normalized_prefix) and len(terminal) > len(
                normalized_prefix
            ):
                terminal = terminal[len(normalized_prefix) :]
                changed = True
                break
    if terminal != parts[-1]:
        keys.add((terminal,))
    return keys
