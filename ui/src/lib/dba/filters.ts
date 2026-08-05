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

// Browser-side mirror of src/admin_ops/kg/filters.py (R6.3, R6.4, R6.5).
//
// Same predicate semantics as the Python EventFilter: AND across the
// categories database / principal / severity / source / time-range, OR within
// a category, plus a DDL-only toggle. apply() is an order-preserving predicate
// filter, so composition is confluent (P-KG4):
//   apply(f2, apply(f1, L)) === apply(f1, apply(f2, L)).
//
// `database` is derived from resource_id with the same pg_ddl shape the Python
// mapper uses; `ddlKind` recovers the leading DDL verb. Used by GraphExplorer
// to filter the timeline and graph client-side without a round trip.

import type { ChangeEvent } from "@/lib/dba/types";

const DDL_KINDS = new Set(["ALTER", "TRUNCATE", "CREATE", "DROP"]);

/** Leading upper-cased alphabetic token of `text`, or "". */
function leadingVerb(text: string): string {
  const head = text.trim().split(/\s+/, 1)[0] ?? "";
  return /^[A-Za-z]+$/.test(head) ? head.toUpperCase() : "";
}

/** Split `pg_ddl:{db}:{object}` -> [db, object] or [null, null]. */
function splitPgDdl(resourceId: string): [string | null, string | null] {
  const parts = resourceId.split(":");
  if (parts.length < 2 || parts[0] !== "pg_ddl") return [null, null];
  const db = parts[1] || null;
  const obj = parts.length >= 3 ? parts.slice(2).join(":") : null;
  return [db, obj && obj.length ? obj : null];
}

/** Database identifier for an event, or null (mirrors parse_resource). */
export function eventDatabase(e: ChangeEvent): string | null {
  if (e.source !== "database") return null;
  const [db] = splitPgDdl(e.resource_id);
  return db;
}

/** DDL verb for an event, or null (mirrors ddl_kind_of). */
export function ddlKind(e: ChangeEvent): string | null {
  if (e.source !== "database") return null;
  const fromSummary = leadingVerb(e.summary);
  if (DDL_KINDS.has(fromSummary)) return fromSummary;
  const [, obj] = splitPgDdl(e.resource_id);
  if (obj) {
    const v = leadingVerb(obj);
    if (DDL_KINDS.has(v)) return v;
  }
  return null;
}

export interface EventFilter {
  databases?: string[] | null;
  principals?: string[] | null;
  severities?: string[] | null;
  sources?: string[] | null;
  /** ISO strings; inclusive bounds. */
  timeFrom?: string | null;
  timeTo?: string | null;
  ddlOnly?: boolean;
}

/** True iff `e` satisfies every active category (AND across, OR within). */
export function matches(f: EventFilter, e: ChangeEvent): boolean {
  if (f.databases != null) {
    const db = eventDatabase(e);
    if (db === null || !f.databases.includes(db)) return false;
  }
  if (f.principals != null && !f.principals.includes(e.actor)) return false;
  if (f.severities != null && !f.severities.includes(e.severity)) return false;
  if (f.sources != null && !f.sources.includes(e.source)) return false;
  if (f.timeFrom != null && e.timestamp < f.timeFrom) return false;
  if (f.timeTo != null && e.timestamp > f.timeTo) return false;
  if (f.ddlOnly && ddlKind(e) === null) return false;
  return true;
}

/** Return the events matching `f`, preserving input order (confluent). */
export function apply(f: EventFilter, events: ChangeEvent[]): ChangeEvent[] {
  return events.filter((e) => matches(f, e));
}

/** Reverse-chronological order with a stable tie-break on event_id (S5). */
export function orderTimeline(events: ChangeEvent[]): ChangeEvent[] {
  return [...events].sort((a, b) => {
    if (a.timestamp !== b.timestamp) return a.timestamp < b.timestamp ? 1 : -1;
    return a.event_id < b.event_id ? 1 : a.event_id > b.event_id ? -1 : 0;
  });
}
