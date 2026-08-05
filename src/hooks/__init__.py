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

"""Agent lifecycle hooks — Tier-3 approval, audit, and gamification.

Submodules are imported explicitly rather than re-exported here. Eager
re-exports previously pulled the whole tool package (and therefore ``strands``)
into any import of this package, which meant the pure Tier-3 decision logic in
:mod:`src.hooks.tier3_gate` could not be imported or tested on its own.

The Tier-3 approval gate lives in:

* :mod:`src.hooks.tier3_gate` — framework-free decision logic (unit tested).
* :mod:`src.hooks.tier3_approval` — the ``strands`` ``HookProvider`` that
  enforces it in the agent loop.
"""
