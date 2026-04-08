"use client";

import { useState, useRef, useCallback } from "react";
import { submitTask, streamTask, getTaskEvidence, type StreamEvent, type TaskEvidence } from "@/lib/api";

type Phase = "idle" | "submitting" | "streaming" | "done" | "error";

const phaseLabel: Record<Phase, string> = {
  idle: "", submitting: "Submitting...", streaming: "Running", done: "Completed", error: "Error",
};

const phaseColorClass: Record<Phase, string> = {
  idle: "c-dim", submitting: "c-yellow", streaming: "c-accent", done: "c-green", error: "c-red",
};

function evtColorClass(type: string) {
  if (type.includes("failed")) return "c-red";
  if (type.includes("passed") || type.includes("delivered")) return "c-green";
  return "c-text";
}

function stepIcon(status: string) {
  if (status === "completed") return "+";
  if (status === "failed") return "x";
  return "-";
}

export default function Home() {
  const [message, setMessage] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [evidence, setEvidence] = useState<TaskEvidence | null>(null);
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState("");
  const cancelRef = useRef<(() => void) | null>(null);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  const busy = phase === "submitting" || phase === "streaming";

  const handleSubmit = useCallback(async () => {
    if (!message.trim() || busy) return;
    setPhase("submitting");
    setEvents([]); setEvidence(null); setError(""); setTaskId("");

    try {
      const res = await submitTask(message.trim());
      setTaskId(res.task_id);
      setPhase("streaming");

      cancelRef.current = streamTask(
        res.task_id,
        (evt) => { setEvents((prev) => [...prev, evt]); setTimeout(scrollToBottom, 50); },
        async () => {
          try { setEvidence(await getTaskEvidence(res.task_id)); } catch { /* optional */ }
          setPhase("done");
        },
        (err) => { setError(err.message); setPhase("error"); },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, [message, busy]);

  return (
    <div className="page">
      <h1>TaijiOS Demo</h1>
      <p className="page-subtitle">Task execution engine — submit, observe, verify</p>

      <div className="input-row">
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="Describe a task..."
          disabled={busy}
        />
        <button type="button" onClick={handleSubmit} disabled={!message.trim() || busy}>
          Run
        </button>
      </div>

      {phase !== "idle" && (
        <div className="status-bar">
          <span className={`status-dot ${phaseColorClass[phase]}${phase === "streaming" ? " pulse" : ""}`} />
          <span className={phaseColorClass[phase]}>{phaseLabel[phase]}</span>
          {taskId && <span className="status-tid">({taskId})</span>}
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      {events.length > 0 && (
        <div className="panel stream-panel">
          <div className="panel-label">Execution Stream</div>
          {events.map((evt, i) => (
            <div key={i} className="evt-row">
              <span className="evt-ts">{new Date(evt.timestamp * 1000).toLocaleTimeString()}</span>
              <span className={evtColorClass(evt.type)}>{evt.type}</span>
              {evt.score !== undefined && <span className="evt-score">score={String(evt.score)}</span>}
            </div>
          ))}
          <div ref={eventsEndRef} />
        </div>
      )}

      {evidence && (
        <div className="panel">
          <div className="panel-label panel-label-lg">Evidence Summary</div>
          <div className="ev-grid">
            <div>Status: <span className={evidence.evidence.succeeded ? "c-green" : "c-red"}>
              {evidence.evidence.succeeded ? "SUCCEEDED" : "FAILED"}
            </span></div>
            <div>Score: <span className="c-yellow">{evidence.evidence.final_score}</span></div>
            <div>Attempts: {evidence.evidence.attempts}</div>
            <div>Self-healed: {evidence.evidence.self_healed ? "Yes" : "No"}</div>
            <div>Reason: {evidence.evidence.reason_code}</div>
          </div>

          {evidence.trace?.steps && (
            <div className="trace-section">
              <div className="panel-label">Trace</div>
              {evidence.trace.steps.map((step, i) => (
                <div key={i} className="trace-step">
                  <span className={step.status === "completed" ? "c-green" : step.status === "failed" ? "c-red" : "c-dim"}>
                    {stepIcon(step.status)}
                  </span>
                  <span>{step.name}</span>
                  {step.output?.score !== undefined && <span className="c-dim">({String(step.output.score)})</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
