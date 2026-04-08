"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { submitTask, streamTask, getTaskEvidence, getTaskStats, type StreamEvent, type TaskEvidence, type TaskStats } from "@/lib/api";

type Phase = "idle" | "submitting" | "streaming" | "done" | "error";

const phaseLabel: Record<Phase, string> = {
  idle: "", submitting: "\u63d0\u4ea4\u4e2d...", streaming: "\u6267\u884c\u4e2d", done: "\u5df2\u5b8c\u6210", error: "\u51fa\u9519",
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
  const [stats, setStats] = useState<TaskStats | null>(null);

  useEffect(() => {
    const fetch = () => { getTaskStats().then(setStats).catch(() => {}); };
    fetch();
    const id = setInterval(fetch, 5000);
    return () => clearInterval(id);
  }, []);

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
      {stats && (
        <div className="sys-bar">
          <span className="sys-dot" />
          <span>系统运行中</span>
          <span className="sys-sep" />
          <span>已完成 <b>{stats.succeeded}</b></span>
          <span className="sys-sep" />
          <span>自愈 <b>{stats.self_healed}</b></span>
          <span className="sys-sep" />
          <span>均分 <b>{stats.avg_score}</b></span>
          {stats.running > 0 && <><span className="sys-sep" /><span className="c-accent">执行中 {stats.running}</span></>}
        </div>
      )}

      <h1>太极OS 演示</h1>
      <p className="page-subtitle">任务执行引擎 — 提交、观察、验证</p>

      <div className="input-row">
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="描述一个任务..."
          disabled={busy}
        />
        <button type="button" onClick={handleSubmit} disabled={!message.trim() || busy}>
          执行
        </button>
      </div>

      {phase !== "idle" && (
        <div className="status-bar">
          <span className={`status-dot ${phaseColorClass[phase]}${phase === "streaming" ? " pulse" : ""}`} />
          <span className={phaseColorClass[phase]}>{phaseLabel[phase]}</span>
          {taskId && <span className="status-tid">任务 {taskId}</span>}
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      {events.length > 0 && (
        <div className="panel stream-panel">
          <div className="panel-label">执行流</div>
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
          <div className="panel-label panel-label-lg">验证摘要</div>
          <div className="ev-grid">
            <div>状态: <span className={evidence.evidence.succeeded ? "c-green" : "c-red"}>
              {evidence.evidence.succeeded ? "通过" : "失败"}
            </span></div>
            <div>评分: <span className="c-yellow">{evidence.evidence.final_score}</span></div>
            <div>尝试次数: {evidence.evidence.attempts}</div>
            <div>自愈: {evidence.evidence.self_healed ? "是" : "否"}</div>
            <div>原因: {evidence.evidence.reason_code}</div>
          </div>

          {evidence.trace?.steps && (
            <div className="trace-section">
              <div className="panel-label">执行轨迹</div>
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

          {evidence.result_content && (
            <div className="trace-section">
              <div className="panel-label">生成内容</div>
              <pre className="gen-content">{evidence.result_content}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
