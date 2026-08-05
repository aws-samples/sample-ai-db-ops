# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pure ChangeEvent -> graph mapper (R2.3-R2.5, R2.9, R3.4, R3.5, R8.4).

This module is pure and fully testable without AWS: :func:`map_change_event`
returns the :class:`GraphMutation` (nodes + edges) implied by one validated
``ChangeEvent``; it does not touch any backend. The live ingestion Lambda and
the batch backfill both call it, so both paths build the same graph.

Mapping (design "ChangeEvent -> graph mapping" table):

* always: one ``ChangeEvent:{event_id}`` node + one ``Principal:{actor}`` node
  + a ``ChangeEvent -MODIFIED_BY-> Principal`` edge.
* when a db is identifiable: ``Database:{db}`` + ``Account:{account_key}`` nodes
  + an ``Account -OWNS-> Database`` edge.
* when a table is identifiable: ``Table:{db}:{table}`` node +
  ``ChangeEvent -RUNS_AGAINST-> Table`` and ``Table -BELONGS_TO-> Database`` edges.
* when the ticket linkage resolves a ticket_id: ``Ticket:{ticket_id}`` node +
  a ``ChangeEvent -CAUSED_BY-> Ticket`` edge.

The mapper is PURE (same input -> same mutation, P-KG1) and REFERENTIALLY SAFE
(every edge endpoint node is included in ``nodes``, P-KG2).

``ddl_kind_of`` reuses the ``pg_ddl`` DDL verb vocabulary (R2.4); the DDL kinds
are ALTER / TRUNCATE / CREATE / DROP. ``parse_resource`` best-effort extracts the
``(database_identifier, qualified_table)`` from a ``database``-source
``resource_id`` shaped ``pg_ddl:{db}:{object}`` (object e.g. ``TABLE shop.orders``).

The ticket linkage is duck-typed: any object exposing ``by_event_id`` (a
``dict[str, str]``) and ``by_resource_pattern`` (a list of ``(regex, ticket_id)``
tuples) is accepted. The concrete ``TicketLinkage`` (Phase 4) is referenced only
under ``TYPE_CHECKING`` so this module never hard-imports ticket code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.admin_ops.changefeed.change_event import ChangeEvent
from src.admin_ops.kg.model import GraphEdge, GraphNode, make_node_id

if TYPE_CHECKING:  # pragma: no cover - typing only; never imported at runtime
    from src.admin_ops.kg.tickets import TicketLinkage  # noqa: F401

# DDL verbs that are DDL_Operations per R2.4. This is the subset of the pg_ddl
# verb vocabulary that constitutes a schema DDL kind surfaced as ``ddl_kind``.
DDL_KINDS: frozenset[str] = frozenset({"ALTER", "TRUNCATE", "CREATE", "DROP"})


@dataclass(frozen=True)
class GraphMutation:
    """The nodes/edges implied by one ChangeEvent. Frozen for purity."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


def ddl_kind_of(event: ChangeEvent) -> str | None:
    """Return ALTER/TRUNCATE/CREATE/DROP if ``event`` is a DDL op, else None.

    Only ``database``-source events carry DDL. The verb is recovered from the
    leading token of the ``summary`` (pg_ddl writes ``"{VERB} on {obj} ..."``),
    falling back to the verb derivable from the ``resource_id`` object segment.
    Non-database sources always return None (R2.4).
    """
    if event.source != "database":
        return None
    verb = _leading_verb(event.summary)
    if verb in DDL_KINDS:
        return verb
    # Fallback: recover the verb from the resource object segment when the
    # summary did not start with a recognizable verb.
    _, _, obj = _split_pg_ddl_resource(event.resource_id)
    if obj is not None:
        obj_verb = _leading_verb(obj)
        if obj_verb in DDL_KINDS:
            return obj_verb
    return None


def parse_resource(event: ChangeEvent) -> tuple[str | None, str | None]:
    """Best-effort ``(database_identifier, qualified_table)`` from ``event``.

    For the ``database`` source, ``resource_id`` is ``pg_ddl:{db}:{object}``
    where ``object`` is like ``TABLE shop.orders``; this extracts ``db`` and,
    when ``object`` begins with ``TABLE``, the ``shop.orders`` table.

    For git / cloudtrail / agent events with no parseable table the result is
    ``(None, None)``. A database may still be identifiable from a ``database``
    source even without a table, in which case the result is ``(db, None)``.
    """
    if event.source != "database":
        return (None, None)
    db, _kind, obj = _split_pg_ddl_resource(event.resource_id)
    if db is None:
        return (None, None)
    table = _table_from_object(obj) if obj is not None else None
    return (db, table)


def map_change_event(
    event: ChangeEvent,
    *,
    ticket_linkage: "Optional[TicketLinkage]" = None,
    account_key: str,
) -> GraphMutation:
    """Return the nodes/edges implied by one validated ``ChangeEvent``.

    Always emits a ``ChangeEvent`` node and a ``Principal`` node (+
    ``MODIFIED_BY``). Adds ``Database``/``Table`` (+ ``RUNS_AGAINST``,
    ``BELONGS_TO``, ``Account``/``OWNS``) when a table/db is identifiable, and a
    ``Ticket`` (+ ``CAUSED_BY``) when the linkage resolves one. Referentially
    safe (P-KG2) and pure (P-KG1).
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # --- always: ChangeEvent node -------------------------------------------
    ddl_kind = ddl_kind_of(event)
    ts_iso = event.timestamp.isoformat()
    ce_props: dict[str, str | int | float | bool | None] = {
        "event_id": event.event_id,
        "source": event.source,
        "severity": event.severity,
        "timestamp": ts_iso,
        "summary": event.summary,
        "details_url": event.details_url,
        # Used by window filtering in the store (R10.2).
        "contributing_ts": ts_iso,
    }
    if ddl_kind is not None:
        ce_props["ddl_kind"] = ddl_kind

    ce_id = make_node_id("ChangeEvent", event.event_id)
    nodes.append(
        GraphNode(node_id=ce_id, type="ChangeEvent", label=event.summary, props=ce_props)
    )

    # --- always: Principal node + MODIFIED_BY edge --------------------------
    principal_id = make_node_id("Principal", event.actor)
    nodes.append(
        GraphNode(
            node_id=principal_id,
            type="Principal",
            label=event.actor,
            props={"actor": event.actor},
        )
    )
    edges.append(
        GraphEdge(edge_type="MODIFIED_BY", source_id=ce_id, target_id=principal_id)
    )

    # --- when a db is identifiable: Database + Account + OWNS ---------------
    db, table = parse_resource(event)
    database_id: str | None = None
    if db is not None:
        database_id = make_node_id("Database", db)
        db_props: dict[str, str | int | float | bool | None] = {"database_id": db}
        if event.engine is not None:
            db_props["engine"] = event.engine
        nodes.append(
            GraphNode(node_id=database_id, type="Database", label=db, props=db_props)
        )
        account_id = make_node_id("Account", account_key)
        nodes.append(
            GraphNode(
                node_id=account_id,
                type="Account",
                label=account_key,
                props={"alias": account_key},
            )
        )
        edges.append(
            GraphEdge(edge_type="OWNS", source_id=account_id, target_id=database_id)
        )

    # --- when a table is identifiable: Table + RUNS_AGAINST + BELONGS_TO ----
    if db is not None and table is not None and database_id is not None:
        table_natural_key = f"{db}:{table}"
        table_id = make_node_id("Table", table_natural_key)
        schema_part, _, table_part = table.partition(".")
        table_props: dict[str, str | int | float | bool | None] = {
            "table_name": table,
            "database_id": db,
        }
        if table_part:
            table_props["schema"] = schema_part
        nodes.append(
            GraphNode(node_id=table_id, type="Table", label=table, props=table_props)
        )
        edges.append(
            GraphEdge(edge_type="RUNS_AGAINST", source_id=ce_id, target_id=table_id)
        )
        edges.append(
            GraphEdge(edge_type="BELONGS_TO", source_id=table_id, target_id=database_id)
        )

    # --- when the linkage resolves a ticket: Ticket + CAUSED_BY -------------
    ticket_id = _resolve_ticket(event, ticket_linkage)
    if ticket_id is not None:
        ticket_node_id = make_node_id("Ticket", ticket_id)
        nodes.append(
            GraphNode(
                node_id=ticket_node_id,
                type="Ticket",
                label=ticket_id,
                props={"ticket_id": ticket_id},
            )
        )
        edges.append(
            GraphEdge(edge_type="CAUSED_BY", source_id=ce_id, target_id=ticket_node_id)
        )

    return GraphMutation(nodes=nodes, edges=edges)


# ─── internal helpers ────────────────────────────────────────────────────────


def _leading_verb(text: str) -> str:
    """Return the upper-cased leading alphabetic token of ``text`` (or "")."""
    stripped = text.strip()
    if not stripped:
        return ""
    head = stripped.split(None, 1)[0]
    return head.upper() if head.isalpha() else ""


def _split_pg_ddl_resource(
    resource_id: str,
) -> tuple[str | None, str | None, str | None]:
    """Split ``pg_ddl:{db}:{object}`` into ``(db, "pg_ddl", object)``.

    ``object`` may contain spaces (e.g. ``TABLE shop.orders``) and is the
    remainder after the second ``:``. Returns ``(None, None, None)`` when the
    resource_id is not pg_ddl-shaped.
    """
    parts = resource_id.split(":", 2)
    if len(parts) < 2 or parts[0] != "pg_ddl":
        return (None, None, None)
    db = parts[1] or None
    obj = parts[2] if len(parts) == 3 and parts[2] != "" else None
    return (db, "pg_ddl", obj)


# ``TABLE`` object segment, e.g. "TABLE shop.orders" -> "shop.orders".
_TABLE_OBJ_RE = re.compile(r"^TABLE\s+(?P<table>[^\s]+)", re.IGNORECASE)


def _table_from_object(obj: str) -> str | None:
    """Return the qualified table name when ``obj`` begins with ``TABLE``."""
    m = _TABLE_OBJ_RE.match(obj.strip())
    if not m:
        return None
    return m.group("table")


def _resolve_ticket(
    event: ChangeEvent, linkage: "Optional[TicketLinkage]"
) -> str | None:
    """Resolve a ticket_id for ``event`` via the duck-typed linkage.

    First an exact ``event_id`` match against ``by_event_id``; then the first
    regex match against ``resource_id`` in ``by_resource_pattern``. Returns
    None when no linkage is supplied or nothing matches.
    """
    if linkage is None:
        return None
    by_event_id = getattr(linkage, "by_event_id", None) or {}
    ticket_id = by_event_id.get(event.event_id)
    if ticket_id is not None:
        return ticket_id
    by_resource_pattern = getattr(linkage, "by_resource_pattern", None) or []
    for pattern, candidate in by_resource_pattern:
        if re.search(pattern, event.resource_id):
            return candidate
    return None
