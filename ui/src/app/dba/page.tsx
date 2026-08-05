/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  ChangeEvent,
  GraphNode,
  GraphResult,
  GatingState,
} from "@/lib/dba/types";
import { apply, orderTimeline, eventDatabase } from "@/lib/dba/filters";
import FilterBar, { type FilterState } from "@/components/dba/FilterBar";
import TimelinePane from "@/components/dba/TimelinePane";
import GraphPane from "@/components/dba/GraphPane";
import EventDetailDrawer from "@/components/dba/EventDetailDrawer";
import NodeDetailDrawer from "@/components/dba/NodeDetailDrawer";
import UnticketedPanel from "@/components/dba/UnticketedPanel";
import GatingNotice from "@/components/dba/GatingNotice";

const USER_HEADER = { "x-user-id": "dbops-user" };

const BADGE_COLOR: Record<string, string> = {
  approved: "border-emerald-700 bg-emerald-950/50 text-emerald-300",
  pending: "border-amber-700 bg-amber-950/50 text-amber-300",
  not_approved: "border-slate-700 bg-slate-800/60 text-slate-400",
  unavailable: "border-rose-800 bg-rose-950/40 text-rose-300",
};

const EMPTY_FILTER: FilterState = {
  databases: [],
  principals: [],
  severities: [],
  sources: [],
  ddlOnly: false,
};

export default function GraphExplorerPage() {
  const [gating, setGating] = useState<GatingState>(null);
  const [healthLoaded, setHealthLoaded] = useState(false);
  const [allEvents, setAllEvents] = useState<ChangeEvent[]>([]);
  const [unticketed, setUnticketed] = useState<{ events: GraphNode[]; complete: boolean }>({
    events: [],
    complete: true,
  });
  const [graph, setGraph] = useState<GraphResult | null>(null);
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const [selectedEvent, setSelectedEvent] = useState<ChangeEvent | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 1. Resolve gating from /api/kg/health on mount (drives the badge + gate).
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/kg/health", { headers: USER_HEADER });
        const body = await res.json();
        setGating((body.gating_state ?? null) as GatingState);
      } catch {
        setGating(null);
      } finally {
        setHealthLoaded(true);
      }
    })();
  }, []);

  // 2. When approved, load the timeline + unticketed list.
  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [tRes, uRes] = await Promise.all([
        fetch("/api/dba/timeline?page=1&page_size=50", { headers: USER_HEADER }),
        fetch("/api/dba/unticketed?days=365", { headers: USER_HEADER }),
      ]);
      const tBody = await tRes.json();
      const uBody = await uRes.json();
      if (tRes.ok && tBody.events) setAllEvents(tBody.events as ChangeEvent[]);
      if (uRes.ok && uBody.events) {
        setUnticketed({ events: uBody.events as GraphNode[], complete: !!uBody.complete });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (gating === "approved") loadData();
  }, [gating, loadData]);

  // 3. Client-side filtered + ordered timeline (filter mirror, P-KG4/S4/S5).
  const filtered = useMemo(() => {
    const f = {
      databases: filter.databases.length ? filter.databases : null,
      principals: filter.principals.length ? filter.principals : null,
      severities: filter.severities.length ? filter.severities : null,
      sources: filter.sources.length ? filter.sources : null,
      ddlOnly: filter.ddlOnly,
    };
    return orderTimeline(apply(f, allEvents));
  }, [filter, allEvents]);

  const databases = useMemo(
    () => Array.from(new Set(allEvents.map(eventDatabase).filter((d): d is string => !!d))).sort(),
    [allEvents],
  );
  const principals = useMemo(
    () => Array.from(new Set(allEvents.map((e) => e.actor))).sort(),
    [allEvents],
  );

  // 4. Re-center the graph on a node (fresh traversal).
  const recenter = useCallback(async (focus: string) => {
    setSelectedNode(null);
    try {
      const res = await fetch(
        `/api/dba/graph?focus=${encodeURIComponent(focus)}&hops=2&days=365`,
        { headers: USER_HEADER },
      );
      const body = await res.json();
      if (res.ok && body.nodes) setGraph(body as GraphResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  // 5. Node click: re-center directly (one consistent drill action).
  const onNodeClick = useCallback(
    async (nodeId: string) => {
      const node = graph?.nodes.find((n) => n.node_id === nodeId) ?? null;
      if (node && node.type !== "ChangeEvent") {
        setSelectedNode(node);
      } else {
        await recenter(nodeId);
      }
    },
    [graph, recenter],
  );

  // An event row opens the detail drawer AND centers the graph on its node.
  const onSelectEvent = useCallback(
    (e: ChangeEvent) => {
      setSelectedEvent(e);
      recenter(`ChangeEvent:${e.event_id}`);
    },
    [recenter],
  );

  // An unticketed item is a GraphNode (ChangeEvent node). Re-center on it, and
  // open the event drawer if we can match it back to a loaded ChangeEvent.
  const onSelectUnticketed = useCallback(
    (node: GraphNode) => {
      const eventId = (node.props?.event_id as string | undefined) ?? null;
      const match = eventId
        ? allEvents.find((e) => e.event_id === eventId) ?? null
        : null;
      if (match) setSelectedEvent(match);
      recenter(node.node_id);
    },
    [allEvents, recenter],
  );

  const badgeKey = gating ?? "unavailable";

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Graph Explorer</h1>
        {healthLoaded && (
          <span className={`rounded border px-2 py-0.5 text-[11px] uppercase tracking-wide ${BADGE_COLOR[badgeKey]}`}>
            {gating ?? "unavailable"}
          </span>
        )}
      </header>

      {error && (
        <div className="rounded border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-200">
          <strong>Error:</strong> {error}
        </div>
      )}

      {healthLoaded && gating !== "approved" ? (
        <GatingNotice state={gating} />
      ) : (
        healthLoaded && (
          <>
            <FilterBar
              state={filter}
              databases={databases}
              principals={principals}
              onChange={setFilter}
            />
            <UnticketedPanel
              events={unticketed.events}
              complete={unticketed.complete}
              onSelect={onSelectUnticketed}
            />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="h-[520px]">
                <TimelinePane events={filtered} onSelect={onSelectEvent} />
              </div>
              <div className="h-[520px]">
                <GraphPane graph={graph} onNodeClick={onNodeClick} />
              </div>
            </div>
          </>
        )
      )}

      <EventDetailDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      <NodeDetailDrawer
        node={selectedNode}
        onRecenter={recenter}
        onClose={() => setSelectedNode(null)}
      />
    </div>
  );
}
