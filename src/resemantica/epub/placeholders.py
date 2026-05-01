from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from xml.etree import ElementTree as ET

from resemantica.epub.models import PlaceholderEntry

PLACEHOLDER_RE = re.compile(r"⟦(/?)([A-Z]+_\d+)⟧")

_TAG_TO_CODE = {
    "a": "A",
    "b": "B",
    "br": "BR",
    "div": "DIV",
    "em": "EM",
    "hr": "HR",
    "i": "I",
    "img": "IMG",
    "ruby": "RUBY",
    "s": "S",
    "span": "SPAN",
    "strong": "B",
    "table": "TABLE",
    "u": "U",
}
_VOID_TAGS = {"br", "hr", "img"}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _attrs_for_json(element: ET.Element) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for key, value in element.attrib.items():
        attributes[_local_name(key)] = value
    return attributes


def _opening_tag(element_name: str, attributes: dict[str, str], void: bool) -> str:
    if attributes:
        attrs = " ".join(f'{name}="{value}"' for name, value in attributes.items())
        if void:
            return f"<{element_name} {attrs} />"
        return f"<{element_name} {attrs}>"
    if void:
        return f"<{element_name} />"
    return f"<{element_name}>"


def build_placeholder_map(
    block_id: str,
    block_element: ET.Element,
) -> tuple[str, list[PlaceholderEntry], list[str]]:
    del block_id
    counters: defaultdict[str, int] = defaultdict(int)
    entries: list[PlaceholderEntry] = []
    warnings: list[str] = []
    rendered_parts: list[str] = []
    entry_by_placeholder: dict[str, PlaceholderEntry] = {}

    def next_placeholder(tag_name: str) -> str:
        code = _TAG_TO_CODE[tag_name]
        counters[code] += 1
        return f"⟦{code}_{counters[code]}⟧"

    def walk(node: ET.Element, stack: list[str], flattened: bool) -> None:
        if node.text:
            rendered_parts.append(node.text)

        for child in list(node):
            tag_name = _local_name(child.tag).lower()
            placeholder_supported = tag_name in _TAG_TO_CODE
            if placeholder_supported:
                placeholder = next_placeholder(tag_name)
                depth = len(stack) + 1
                parent_placeholder = stack[-1] if stack else None
                is_void = tag_name in _VOID_TAGS
                should_emit = not flattened and depth <= 3

                entry = PlaceholderEntry(
                    placeholder=placeholder,
                    element=tag_name,
                    attributes=_attrs_for_json(child),
                    original_xhtml=_opening_tag(tag_name, _attrs_for_json(child), is_void),
                    parent_placeholder=parent_placeholder,
                    depth=depth,
                    closing_order=None,
                    emitted=should_emit,
                )
                entries.append(entry)
                entry_by_placeholder[placeholder] = entry

                if should_emit:
                    rendered_parts.append(placeholder)

                if not is_void:
                    walk(
                        child,
                        stack=stack + [placeholder],
                        flattened=flattened or depth > 3,
                    )
                    if should_emit:
                        rendered_parts.append(f"⟦/{placeholder[1:]}")
            else:
                walk(child, stack=stack, flattened=flattened)

            if child.tail:
                rendered_parts.append(child.tail)

    walk(block_element, stack=[], flattened=False)

    root_lookup: dict[str, str] = {}
    for entry in entries:
        ancestor = entry
        while ancestor.parent_placeholder is not None:
            ancestor = entry_by_placeholder[ancestor.parent_placeholder]
        root_lookup[entry.placeholder] = ancestor.placeholder

    members_by_root: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        if not entry.emitted:
            continue
        members_by_root[root_lookup[entry.placeholder]].append(entry.placeholder)

    for idx, entry in enumerate(entries):
        if entry.parent_placeholder is not None:
            continue
        members = members_by_root.get(entry.placeholder, [])
        if not members:
            warnings.append(f"{entry.placeholder} was flattened and has no emitted members.")
            closing_order: list[str] | None = [entry.placeholder]
        else:
            closing_order = list(reversed(members))
        entries[idx] = replace(entry, closing_order=closing_order)

    return "".join(rendered_parts), entries, warnings


def restore_from_placeholders(
    text: str,
    entries: list[PlaceholderEntry],
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    rendered_parts: list[str] = []
    last = 0

    entry_by_placeholder = {entry.placeholder: entry for entry in entries}
    entry_by_key = {entry.placeholder[1:-1]: entry for entry in entries}

    root_by_key: dict[str, str] = {}
    for entry in entries:
        current = entry
        while current.parent_placeholder is not None:
            current = entry_by_placeholder[current.parent_placeholder]
        root_by_key[entry.placeholder[1:-1]] = current.placeholder[1:-1]

    closing_seen: dict[str, list[str]] = defaultdict(list)
    stack: list[str] = []

    for match in PLACEHOLDER_RE.finditer(text):
        rendered_parts.append(text[last : match.start()])
        is_closing = bool(match.group(1))
        key = match.group(2)

        mapped_entry = entry_by_key.get(key)
        if mapped_entry is None:
            warnings.append(f"Unknown placeholder token: {match.group(0)}")
            rendered_parts.append(match.group(0))
            last = match.end()
            continue

        tag_name = mapped_entry.element
        is_void = tag_name in _VOID_TAGS
        root_key = root_by_key.get(key, key)

        if is_closing:
            closing_seen[root_key].append(f"⟦{key}⟧")
            if key not in stack:
                warnings.append(f"Unexpected closing placeholder: {match.group(0)}")
                rendered_parts.append(f"</{tag_name}>")
            else:
                while stack and stack[-1] != key:
                    wrong_key = stack.pop()
                    wrong_entry = entry_by_key[wrong_key]
                    warnings.append(
                        f"Closing placeholder order mismatch: expected ⟦/{wrong_key}⟧ before {match.group(0)}."
                    )
                    rendered_parts.append(f"</{wrong_entry.element}>")
                if stack and stack[-1] == key:
                    stack.pop()
                    rendered_parts.append(f"</{tag_name}>")
        else:
            rendered_parts.append(mapped_entry.original_xhtml)
            if not is_void:
                stack.append(key)

        last = match.end()

    rendered_parts.append(text[last:])

    while stack:
        dangling = stack.pop()
        dangling_entry = entry_by_key[dangling]
        warnings.append(f"Dangling opening placeholder closed automatically: ⟦{dangling}⟧")
        rendered_parts.append(f"</{dangling_entry.element}>")

    for entry in entries:
        if entry.parent_placeholder is not None or entry.closing_order is None:
            continue
        root_key = entry.placeholder[1:-1]
        seen = closing_seen.get(root_key, [])
        expected = entry.closing_order
        if seen and seen != expected:
            warnings.append(
                f"Closing order warning for {entry.placeholder}: expected {expected}, got {seen}."
            )

    return "".join(rendered_parts), warnings
