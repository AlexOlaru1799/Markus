"""Playwright-free XML helpers for SAGA Facturi / Încasări / Plăți files."""

from __future__ import annotations

from xml.etree import ElementTree as ET


def local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def findall(node: ET.Element, tag: str) -> list[ET.Element]:
    tag_l = tag.casefold()
    return [child for child in node.iter() if local(child.tag).casefold() == tag_l]


def find(node: ET.Element, tag: str) -> ET.Element | None:
    matches = findall(node, tag)
    return matches[0] if matches else None


def child_text(node: ET.Element, tag: str) -> str:
    child = None
    tag_l = tag.casefold()
    for item in list(node):
        if local(item.tag).casefold() == tag_l:
            child = item
            break
    if child is None:
        child = find(node, tag)
    if child is None or child.text is None:
        return ""
    return str(child.text).strip()


def number(value: str | None) -> float:
    try:
        return float((value or "0").replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


def root_kind(root: ET.Element) -> str:
    kind = local(root.tag)
    lowered = kind.casefold()
    if lowered == "facturi":
        return "Facturi"
    if lowered == "incasari":
        return "Incasari"
    if lowered == "plati":
        return "Plati"
    return kind
