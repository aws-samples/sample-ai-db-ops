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

"""Lazy-singleton template registry.

Loads every YAML file under `src/admin_ops/registry/templates/<engine>/`
once at first use, with a `reload()` for hot updates. When a file fails
to load, the loader records the failure, leaves the rest of the registry
intact, and (later, once Phase 1D lands) emits a Change_Event on the
`agent` source.

Validates: R1.3, R1.4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from src.admin_ops.registry.render import RenderedQuery, render_template
from src.admin_ops.registry.schema import TemplateLoadError, TemplateSpec

LOG = logging.getLogger(__name__)
_TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"


class TemplateNotFoundError(KeyError):
    pass


@dataclass
class LoadFailure:
    path: str
    template_id: str | None
    reason: str


@dataclass
class TemplateRegistry:
    _specs: dict[str, TemplateSpec] = field(default_factory=dict)
    _failures: list[LoadFailure] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock, repr=False)
    _root: Path = field(default=_TEMPLATES_ROOT)

    def load(self, root: Path | None = None) -> None:
        """Read every `*.yaml` or `*.yml` under the templates root."""
        with self._lock:
            self._specs.clear()
            self._failures.clear()
            search_root = root or self._root
            if not search_root.exists():
                LOG.warning("template root %s does not exist", search_root)
                return
            for path in sorted(search_root.rglob("*.y*ml")):
                if not path.is_file():
                    continue
                try:
                    spec = TemplateSpec.parse_file(path)
                except TemplateLoadError as exc:
                    self._failures.append(
                        LoadFailure(
                            path=str(path),
                            template_id=path.stem,
                            reason=str(exc),
                        )
                    )
                    LOG.error("template registry load failure: %s", exc)
                    _emit_load_failure_change_event(path, exc)
                    continue
                self._specs[spec.template_id] = spec

    def reload(self) -> None:
        """Re-read disk; useful when admins push template edits."""
        self.load()

    def get(self, template_id: str) -> TemplateSpec | None:
        return self._specs.get(template_id)

    def must_get(self, template_id: str) -> TemplateSpec:
        spec = self.get(template_id)
        if spec is None:
            raise TemplateNotFoundError(template_id)
        return spec

    def render(self, template_id: str, params: Mapping[str, Any]) -> RenderedQuery:
        return render_template(self.must_get(template_id), params)

    def all(self) -> list[TemplateSpec]:
        return list(self._specs.values())

    def failures(self) -> list[LoadFailure]:
        return list(self._failures)


# ─── Singleton ──────────────────────────────────────────────────────────────

registry = TemplateRegistry()


def _emit_load_failure_change_event(path: Path, exc: BaseException) -> None:
    """Emit a Change_Event on the `agent` source describing the failure (R1.4).

    Constructs a high-severity Change_Event naming the offending registry
    path and persists it via the change-feed store. The change-feed import is
    lazy to avoid a circular import, and the whole thing is wrapped in a
    try/except: registry load must never crash because the change feed is
    unavailable. The structured ERROR log below is the always-on fallback.
    """
    LOG.error(
        "load_failure_change_event path=%s reason=%s",
        path,
        type(exc).__name__ + ": " + str(exc),
    )
    try:
        from datetime import datetime, timezone

        from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
        from src.admin_ops.changefeed.store import put_event

        ts = datetime.now(timezone.utc)
        resource_id = str(path)
        actor = "registry-loader"
        event = ChangeEvent(
            event_id=make_event_id("agent", actor, ts, resource_id),
            source="agent",
            actor=actor,
            timestamp=ts,
            engine=None,
            resource_id=resource_id,
            severity="high",
            summary=f"Template registry failed to load {path.name}: "
            f"{type(exc).__name__}",
            details_url=f"file://{path}",
            raw_payload_ref=f"registry-load-failure:{path.name}",
        )
        put_event(event)
    except Exception as emit_exc:  # noqa: BLE001 - never let the feed break loading
        LOG.error(
            "failed to emit load-failure change event path=%s reason=%s",
            path,
            type(emit_exc).__name__ + ": " + str(emit_exc),
        )
