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

// Shared DBA View types mirroring the Python kg models (model.py, query.py).
// Kept presentational; the server is the source of truth for graph data.

export type Source = "git" | "cloudtrail" | "agent" | "database";
export type Severity = "low" | "medium" | "high" | "critical";

export interface ChangeEvent {
  event_id: string;
  source: Source;
  actor: string;
  timestamp: string;
  engine: "postgresql" | "mysql" | "oracle" | "dynamodb" | null;
  resource_id: string;
  severity: Severity;
  summary: string;
  details_url: string;
  raw_payload_ref: string;
}

export interface GraphNode {
  node_id: string;
  type: string;
  label: string;
  props: Record<string, unknown>;
}

export interface GraphEdge {
  edge_type: string;
  source_id: string;
  target_id: string;
}

export interface GraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus: string;
  window: Record<string, string>;
}

export type GatingState = "pending" | "approved" | "not_approved" | null;
