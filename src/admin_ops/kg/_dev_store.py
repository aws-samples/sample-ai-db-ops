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

"""JSON-seeded in-memory graph backend for the no-Neptune demo (R2.1, R4.3).

Activated when ``ADMIN_DEV_BYPASS=1`` (the demo escape hatch), mirroring
``src/admin_ops/changefeed/_dev_store.py``. It builds an
:class:`InMemoryGraphBackend` in-process — with **no AWS** — by:

1. reading the existing dev change-feed JSON (the same file
   ``changefeed/_dev_store.py`` persists), so the graph reflects whatever the
   live demo change feed has captured;
2. loading the seeded :class:`~src.admin_ops.kg.tickets.SeededTicketSource`
   linkage so DDL on a known table links to its Change_Request; and
3. running every event through the same pure ``ingest.map_change_event`` and
   upserting the result.

Because ingestion is idempotent (P-KG1) and the mapper is referentially safe
(P-KG2), the seeded backend is a faithful in-process stand-in for the Neptune
backend: the same query layer runs unchanged against it.
"""

from __future__ import annotations

from src.admin_ops.changefeed._dev_store import JsonFileChangeFeedBackend
from src.admin_ops.config.require import optional_config
from src.admin_ops.kg import tickets
from src.admin_ops.kg.ingest import map_change_event
from src.admin_ops.kg.store import InMemoryGraphBackend


def _account_key() -> str:
    """Return the placeholder account key used to label Account nodes.

    Read from config (``account.alias``) with a placeholder default so the dev
    path never embeds a real account id. Used only as a graph label.
    """
    return optional_config("account", "alias", default="dbops-user")


def build_seeded_backend() -> InMemoryGraphBackend:
    """Build an :class:`InMemoryGraphBackend` from the dev change-feed + tickets.

    Reads the dev change-feed JSON via the existing
    :class:`JsonFileChangeFeedBackend`, resolves the seeded ticket linkage, and
    upserts the mutation for every event. Pure in-process; no AWS.
    """
    backend = InMemoryGraphBackend()
    feed = JsonFileChangeFeedBackend()
    linkage = tickets.get_ticket_source().linkage()
    account_key = _account_key()

    for event in feed.all_events():
        mutation = map_change_event(
            event, ticket_linkage=linkage, account_key=account_key
        )
        backend.upsert(mutation)

    return backend
