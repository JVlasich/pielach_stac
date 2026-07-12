"""Placement resolver.

Buckets Products into placement Nodes: one flat node (campaign collection body)
plus one node per subcollection group. Starts from discover's auto tile groups
(product.group), then applies the sidecar hierarchy block:
  placement: {product_id: group_name | ~}   pin into a group / force flat
  groups:    {group_name: {title, description}}   subcollection metadata
Pure, no pystac.
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Node:
    name: str | None            # None = flat in the campaign collection
    title: str | None = None
    description: str | None = None
    products: list = field(default_factory=list)

    def __str__(self) -> str:
        target = self.name if self.name else "<flat>"
        return f"Node {target}  ({len(self.products)} products)"


def resolve_hierarchy(products, hier: dict | None = None) -> list[Node]:
    """Products + sidecar hierarchy block -> [flat Node, *group Nodes].
    Flat node is always first. placement overrides win over product.group;
    a group named only in 'groups' with no products is warned and dropped."""
    hier = hier or {}
    placement = hier.get("placement") or {}
    groups_meta = hier.get("groups") or {}

    known = {p.id for p in products}
    for pid in sorted(set(placement) - known):
        log.warning(f"hierarchy placement for unknown product id: {pid}")

    buckets: dict = {}
    for p in products:
        g = placement.get(p.id, p.group)  # explicit null in placement = force flat
        buckets.setdefault(g, []).append(p)

    nodes = [Node(None, products=buckets.pop(None, []))]
    for name in sorted(buckets):
        meta = groups_meta.get(name) or {}
        nodes.append(Node(name, meta.get("title"), meta.get("description"), buckets[name]))

    for name in sorted(set(groups_meta) - {n.name for n in nodes}):
        log.warning(f"hierarchy group {name!r} has no products, dropped")
    return nodes
