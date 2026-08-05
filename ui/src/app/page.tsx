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

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import ChatPanel from "@/components/ChatPanel";
import FleetPanel from "@/components/FleetPanel";
import GamificationBar from "@/components/GamificationBar";
import TracePanel, { TraceStep } from "@/components/TracePanel";
import CloneModal, { CloneConfig } from "@/components/CloneModal";
import { newSessionId } from "@/lib/session";

export default function Home() {
  const [selectedDb, setSelectedDb] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("postgresql");
  const [traceVisible, setTraceVisible] = useState(true);
  const [traceSteps, setTraceSteps] = useState<TraceStep[]>([]);
  const [cloneModalOpen, setCloneModalOpen] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  // Lazily initialised so the CSPRNG is only touched on the client.
  const [currentSessionId, setCurrentSessionId] = useState(newSessionId);

  const addTraceStep = (step: Omit<TraceStep, "id" | "timestamp">) => {
    // Math.random is fine here: this id is only a React list key for the local
    // trace panel. It carries no authorization meaning and never leaves the
    // browser. Session identifiers use the CSPRNG instead — see lib/session.ts.
    setTraceSteps(prev => [...prev, { ...step, id: `${Date.now()}-${Math.random()}`, timestamp: new Date() }]);
  };

  const startNewSession = () => {
    const newId = newSessionId();
    setCurrentSessionId(newId);
    setTraceSteps([{ id: `${Date.now()}`, type: "session_start", label: "New Session", status: "success", timestamp: new Date() }]);
    return newId;
  };

  const handleCloneSubmit = (config: CloneConfig) => {
    addTraceStep({ type: "user_input", label: "Clone DB requested", status: "success", detail: `${config.tables.length} tables to ${config.targetEnv}` });
    addTraceStep({ type: "tool_call", label: "replicate_table_with_masking", status: "running", detail: config.tables.map(t => t.name).join(", ") });

    setTimeout(() => {
      addTraceStep({ type: "agent_response", label: "Clone complete", status: "success", duration: 4500, detail: `${config.tables.length} tables replicated` });
    }, 3000);
  };

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <Sidebar selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} />

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top Bar */}
        <GamificationBar onToggleTrace={() => setTraceVisible(!traceVisible)} />

        {/* Content Area */}
        <div className="flex flex-1 overflow-hidden">
          {/* Fleet Panel */}
          <FleetPanel
            selectedDb={selectedDb}
            onSelectDb={setSelectedDb}
            agentType={selectedAgent}
            onCloneClick={() => setCloneModalOpen(true)}
            onQuickAction={(prompt) => { startNewSession(); setPendingPrompt(prompt); }}
          />

          {/* Chat Panel */}
          <ChatPanel
            selectedDb={selectedDb}
            agentType={selectedAgent}
            onTraceUpdate={addTraceStep}
            externalPrompt={pendingPrompt}
            onExternalPromptConsumed={() => setPendingPrompt(null)}
          />

          {/* Trace Panel */}
          <TracePanel steps={traceSteps} isVisible={traceVisible} onToggle={() => setTraceVisible(false)} sessionId={currentSessionId} />
        </div>
      </div>

      {/* Clone Modal */}
      <CloneModal
        isOpen={cloneModalOpen}
        onClose={() => setCloneModalOpen(false)}
        onSubmit={handleCloneSubmit}
        sourceDb={selectedDb || "dbops-demo-aurora-pg"}
      />
    </div>
  );
}
