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
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import SqlEditorDrawer, { Engine } from "./SqlEditorDrawer";
import CustomButtonModal from "./CustomButtonModal";
import { withUserHeader } from "@/lib/auth/client";

interface CustomButton {
  button_id: string;
  owner_user_id: string;
  team_id: string | null;
  label: string;
  icon: string;
  engine: Engine;
  target_scope: string;
  body_kind: "sql" | "prompt";
  body: string;
  confirmation_required: boolean;
  tier_hint: 1 | 2 | 3;
  position: number;
}

interface CustomButtonsGroupProps {
  engine: Engine;
  /** Called when a body_kind=prompt button is clicked. Forwards to /api/invoke. */
  onPromptInvoke?: (prompt: string) => void;
}

function SortableTile({
  button,
  onClick,
  onDelete,
}: {
  button: CustomButton;
  onClick: () => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: button.button_id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group relative rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-[11px] font-medium text-slate-300 hover:border-blue-500 hover:bg-blue-950/40 hover:text-blue-300 transition cursor-pointer"
    >
      <div
        className="flex items-center gap-1"
        onClick={onClick}
        role="button"
        tabIndex={0}
      >
        <span>{button.icon || (button.body_kind === "sql" ? "⚡" : "💬")}</span>
        <span className="truncate">{button.label}</span>
      </div>
      <div className="absolute top-1 right-1 hidden gap-1 group-hover:flex">
        <button
          {...attributes}
          {...listeners}
          className="rounded bg-slate-900/80 text-[9px] px-1 text-slate-400 hover:text-slate-200 cursor-grab active:cursor-grabbing"
          aria-label="Drag to reorder"
          title="Drag to reorder"
        >
          ⋮⋮
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="rounded bg-slate-900/80 text-[9px] px-1 text-rose-400 hover:text-rose-300"
          aria-label="Delete button"
          title="Delete"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export default function CustomButtonsGroup({
  engine,
  onPromptInvoke,
}: CustomButtonsGroupProps) {
  const [buttons, setButtons] = useState<CustomButton[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorBody, setEditorBody] = useState("");
  const [editorTitle, setEditorTitle] = useState("");

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`/api/admin/buttons?engine=${engine}`, {
        headers: withUserHeader(),
        credentials: "include",
      });
      if (!res.ok) {
        setButtons([]);
        return;
      }
      const data = (await res.json()) as { buttons: CustomButton[] };
      setButtons(
        (data.buttons || []).slice().sort((a, b) => a.position - b.position),
      );
    } catch {
      setButtons([]);
    } finally {
      setLoaded(true);
    }
  }, [engine]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = buttons.findIndex((b) => b.button_id === active.id);
      const newIndex = buttons.findIndex((b) => b.button_id === over.id);
      if (oldIndex < 0 || newIndex < 0) return;
      const next = arrayMove(buttons, oldIndex, newIndex);
      setButtons(next);
      try {
        await fetch("/api/admin/buttons/reorder", {
          method: "POST",
          headers: withUserHeader({ "content-type": "application/json" }),
          credentials: "include",
          body: JSON.stringify(
            next.map((b, i) => ({ button_id: b.button_id, position: i })),
          ),
        });
      } catch {
        // Server failed; refresh from server.
        refresh();
      }
    },
    [buttons, refresh],
  );

  const onClickButton = useCallback(
    (b: CustomButton) => {
      if (b.body_kind === "sql") {
        setEditorBody(b.body);
        setEditorTitle(b.label);
        setEditorOpen(true);
      } else if (onPromptInvoke) {
        onPromptInvoke(b.body);
      }
    },
    [onPromptInvoke],
  );

  const onDelete = useCallback(
    async (id: string) => {
      if (!confirm("Delete this button?")) return;
      await fetch(`/api/admin/buttons/${id}`, {
        method: "DELETE",
        headers: withUserHeader(),
        credentials: "include",
      });
      refresh();
    },
    [refresh],
  );

  const onCreated = useCallback(() => {
    setModalOpen(false);
    refresh();
  }, [refresh]);

  if (!loaded) return null;

  return (
    <div className="mt-5">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          <span>🧩</span>
          <span>Custom Buttons</span>
        </h3>
        <button
          onClick={() => setModalOpen(true)}
          className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          + Add
        </button>
      </div>

      {buttons.length === 0 ? (
        <p className="text-[11px] text-slate-500">
          No custom buttons yet. Click <strong>+ Add</strong> to create one.
        </p>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={buttons.map((b) => b.button_id)} strategy={rectSortingStrategy}>
            <div className="grid grid-cols-2 gap-1.5">
              {buttons.map((b) => (
                <SortableTile
                  key={b.button_id}
                  button={b}
                  onClick={() => onClickButton(b)}
                  onDelete={() => onDelete(b.button_id)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <CustomButtonModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        engine={engine}
        onCreated={onCreated}
      />

      <SqlEditorDrawer
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        engine={engine}
        initialBody={editorBody}
        title={editorTitle}
      />
    </div>
  );
}
