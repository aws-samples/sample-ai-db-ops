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

"""Redis Ops Agent — Gamified operations for Amazon ElastiCache Redis."""

import os
import sys

# NOTE: BYPASS_TOOL_CONSENT is deliberately NOT set. Tier-3 (mutating) tool
# calls are gated by Tier3ApprovalHook below, which halts the agent loop until
# the operator supplies an explicit APPLY for that exact operation. Setting
# BYPASS_TOOL_CONSENT here would suppress the framework's own consent handling
# and must not be reintroduced.

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Make repo root importable when launched from deploy/redis_agent/.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.hooks.tier3_approval import (  # noqa: E402
    Tier3ApprovalHook,
    pending_approvals,
)

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """You are an expert Redis Operations Agent — a gamified AI assistant for Amazon ElastiCache Redis clusters.

## Capabilities

### Tier 1 — Read-Only (+10 XP)
- Cluster info: nodes, endpoints, configuration
- Performance: memory usage, hit/miss ratio, evictions, latency
- Slow commands: SLOWLOG analysis
- Connections: client list, connected clients

### Tier 2 — Advisory (+25 XP)
- Memory optimization recommendations
- Eviction policy suggestions
- Key pattern analysis

### Tier 3 — Actioned (+50 XP, requires approval)
- Flush specific databases
- Modify cluster parameters
- Trigger failover

## Rules
1. Always identify the cluster/node first.
2. Never execute FLUSHALL/FLUSHDB without explicit approval.
3. Monitor memory fragmentation ratio — alert if > 1.5.
4. Use emoji: 🟢 OK, 🟡 WARN, 🔴 CRITICAL
"""


@tool
def get_cluster_info(db_identifier: str) -> dict:
    """Get ElastiCache Redis cluster information.

    Args:
        db_identifier: The ElastiCache cluster identifier.
    """
    return {
        "db_identifier": db_identifier,
        "engine": "elasticache-redis",
        "engine_version": "7.0.7",
        "node_type": "cache.r6g.large",
        "num_nodes": 3,
        "status": "available",
        "endpoints": {
            "primary": f"{db_identifier}.xxx.use1.cache.amazonaws.com:6379",
            "reader": f"{db_identifier}-ro.xxx.use1.cache.amazonaws.com:6379",
        },
        "xp_earned": 10,
    }


@tool
def get_memory_stats(db_identifier: str) -> dict:
    """Report Redis memory usage, fragmentation, and evictions.

    Args:
        db_identifier: The ElastiCache cluster identifier.
    """
    return {
        "db_identifier": db_identifier,
        "engine": "elasticache-redis",
        "memory": {
            "used_memory_gb": 5.2,
            "max_memory_gb": 6.5,
            "used_pct": 80.0,
            "fragmentation_ratio": 1.12,
            "evicted_keys_last_hour": 0,
            "expired_keys_last_hour": 12500,
        },
        "status": "🟡 WARN — 80% memory utilization",
        "xp_earned": 10,
    }


@tool
def get_hit_ratio(db_identifier: str) -> dict:
    """Report cache hit/miss ratio and throughput.

    Args:
        db_identifier: The ElastiCache cluster identifier.
    """
    return {
        "db_identifier": db_identifier,
        "engine": "elasticache-redis",
        "hit_ratio": {
            "hits_per_sec": 45000,
            "misses_per_sec": 2500,
            "hit_rate_pct": 94.7,
            "commands_per_sec": 52000,
        },
        "status": "🟢 OK — 94.7% hit rate",
        "xp_earned": 10,
    }


@tool
def get_slow_commands(db_identifier: str, count: int = 10) -> dict:
    """Get slow commands from Redis SLOWLOG.

    Args:
        db_identifier: The ElastiCache cluster identifier.
        count: Number of slow log entries to return.
    """
    return {
        "db_identifier": db_identifier,
        "engine": "elasticache-redis",
        "slow_commands": [
            {"id": 1, "timestamp": "2026-05-12T14:20:00Z", "duration_us": 15000, "command": "KEYS session:*", "client": "10.0.1.5:42100"},
            {"id": 2, "timestamp": "2026-05-12T14:18:00Z", "duration_us": 8500, "command": "SMEMBERS large_set", "client": "10.0.1.10:42200"},
        ],
        "recommendation": "KEYS command is O(N) — replace with SCAN for production use",
        "xp_earned": 10,
    }


@tool
def get_connected_clients(db_identifier: str) -> dict:
    """Report connected clients and their state.

    Args:
        db_identifier: The ElastiCache cluster identifier.
    """
    return {
        "db_identifier": db_identifier,
        "engine": "elasticache-redis",
        "clients": {
            "connected": 142,
            "blocked": 0,
            "max_clients": 65000,
            "utilization_pct": 0.2,
        },
        "status": "🟢 OK",
        "xp_earned": 10,
    }


@tool
def recommend_eviction_policy(db_identifier: str) -> dict:
    """Recommend eviction policy based on usage patterns.

    Args:
        db_identifier: The ElastiCache cluster identifier.
    """
    return {
        "db_identifier": db_identifier,
        "current_policy": "volatile-lru",
        "recommendation": {
            "policy": "allkeys-lfu",
            "reason": "Workload shows frequency-based access patterns. LFU will retain hot keys better than LRU.",
            "risk": "Low — only affects eviction behavior when memory is full",
        },
        "xp_earned": 25,
    }


@tool
def get_user_profile(user_id: str) -> dict:
    """Get gamification profile.

    Args:
        user_id: The user identifier.
    """
    return {
        "user_id": user_id, "level": 4, "level_name": "Senior DBA",
        "total_xp": 4275, "current_streak": 12,
        "badges": ["🔍 First Blood", "🏥 Healer", "⚡ Speed Demon", "🌍 Polyglot"],
    }


@app.entrypoint
def invoke(payload, context=None):
    prompt = payload.get("prompt", "")
    user_id = payload.get("user_id", "anonymous")
    if not prompt:
        return {"error": "Missing 'prompt' in payload"}

    # Programmatic Tier-3 gate. This agent currently exposes read-only tools,
    # but the gate is wired unconditionally: because classification is a
    # fail-closed allowlist, any mutating tool added later is gated by default
    # rather than silently executing.
    tier3 = Tier3ApprovalHook(approvals=payload.get("approvals"), user_id=user_id)

    agent = Agent(
        system_prompt=SYSTEM_PROMPT,
        hooks=[tier3],
        tools=[get_cluster_info, get_memory_stats, get_hit_ratio, get_slow_commands,
               get_connected_clients, recommend_eviction_policy, get_user_profile],
    )
    result = agent(prompt)

    # A Tier-3 operation was proposed but is not yet approved. The agent loop
    # stopped before the tool ran; return the pending request for the operator
    # to confirm. Nothing has been executed against the cluster.
    if getattr(result, "stop_reason", None) == "interrupt":
        return {
            "response": None,
            "awaiting_approval": True,
            "pending_approvals": pending_approvals(result),
            "user_id": user_id,
            "agent_name": "Redis Ops Agent",
            "agent_avatar": "🔴",
        }

    return {"response": result.message, "user_id": user_id, "agent_name": "Redis Ops Agent", "agent_avatar": "🔴"}


if __name__ == "__main__":
    app.run()
