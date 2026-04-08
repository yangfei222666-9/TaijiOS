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

function evtLabel(type: string): string {
  const map: Record<string, string> = {
    "task.started": "任务启动",
    "step.completed": "步骤完成",
    "validation.passed": "验证通过",
    "validation.failed": "验证失败",
    "task.delivered": "任务交付",
    "task.done": "任务结束",
    "task.dlq": "任务进入死信队列",
  };
  return map[type] || type;
}

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

const checkLabel: Record<string, string> = {
  character_consistency: "角色一致性",
  style_consistency: "风格一致性",
  shot_continuity: "连贯性",
  subtitle_safety: "可读性",
};

const checkHint: Record<string, string> = {
  character_consistency: "回答是否保持统一的身份和语气",
  style_consistency: "语调和表达风格是否前后一致",
  shot_continuity: "逻辑是否连贯，有无突兀跳转",
  subtitle_safety: "内容是否清晰、易读、格式规范",
};

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
          <span>Gateway <b className="c-green">{stats.gateway}</b></span>
          <span className="sys-sep" />
          <span>Task API <b className="c-green">{stats.task_api}</b></span>
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
              <span className={evtColorClass(evt.type)}>{evtLabel(evt.type)}</span>
              {evt.score !== undefined && <span className="evt-score">评分={String(evt.score)}</span>}
              {evt.rev !== undefined && <span className="c-dim">第{String(evt.rev)}轮</span>}
              {Array.isArray(evt.failed_checks) && evt.failed_checks.length > 0 && <span className="c-red">{(evt.failed_checks as string[]).join(", ")}</span>}
            </div>
          ))}
          <div ref={eventsEndRef} />
        </div>
      )}

      {evidence && (
        <div className="panel">
          <div className="panel-label panel-label-lg">验证摘要</div>
          {evidence.evidence.validator && (
            <div className="validator-tag">验证器: {evidence.evidence.validator}</div>
          )}
          <div className="ev-grid">
            <div>状态: <span className={evidence.evidence.succeeded ? "c-green" : "c-red"}>
              {evidence.evidence.succeeded ? "通过" : "失败"}
            </span></div>
            <div>评分: <span className="c-yellow">{evidence.evidence.final_score}</span></div>
            <div>尝试次数: {evidence.evidence.attempts}</div>
            <div>自愈: {evidence.evidence.self_healed ? "是" : "否"}</div>
            <div>原因: {evidence.evidence.reason_code}</div>
          </div>

          {evidence.evidence.checks && (
            <div className="trace-section">
              <div className="panel-label">四维检查</div>
              <div className="checks-grid">
                {Object.entries(evidence.evidence.checks).map(([name, check]) => (
                  <div key={name} className="check-row">
                    <span className={check.passed ? "c-green" : "c-red"}>{check.passed ? "+" : "x"}</span>
                    <span className="check-name">{checkLabel[name] || name}</span>
                    <span className="c-yellow">{check.score}</span>
                    <span className="c-dim">{checkHint[name] || ""}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {evidence.evidence.fix_suggestions && evidence.evidence.fix_suggestions.length > 0 && (
            <div className="trace-section">
              <div className="panel-label">修复建议</div>
              {evidence.evidence.fix_suggestions.map((s, i) => (
                <div key={i} className="fix-row">{s}</div>
              ))}
            </div>
          )}

          {evidence.hexagram && (
            <div className="trace-section">
              <div className="panel-label">卦象决策</div>
              <div className="hex-header">
                <span className="hex-name">{evidence.hexagram.name}</span>
                <span className={`hex-risk ${evidence.hexagram.risk === "低风险" ? "c-green" : evidence.hexagram.risk === "中风险" ? "c-yellow" : "c-red"}`}>{evidence.hexagram.risk}</span>
                <span className="hex-bits">{evidence.hexagram.bits}</span>
              </div>
              <div className="hex-meaning">{evidence.hexagram.meaning}</div>
              <div className="hex-lines">
                {Object.entries(evidence.hexagram.lines).map(([name, score]) => (
                  <div key={name} className="hex-line-row">
                    <span className={score >= 0.6 ? "c-green" : score <= 0.4 ? "c-red" : "c-yellow"}>{score >= 0.6 ? "阳" : score <= 0.4 ? "阴" : "变"}</span>
                    <span className="hex-line-name">{name}</span>
                    <span className="c-dim">{score}</span>
                  </div>
                ))}
              </div>
              {evidence.hexagram.actions.length > 0 && (
                <div className="hex-actions">
                  <span className="c-dim">推荐动作:</span>
                  {evidence.hexagram.actions.map((a, i) => (
                    <span key={i} className="hex-action-tag">{a}</span>
                  ))}
                </div>
              )}
            </div>
          )}

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

      {/* Engine capability indicators */}
      <div className="engine-bar">
        <div className="panel-label">引擎状态</div>
        <div className="engine-grid">
          <div className="engine-item"><span className="eng-dot c-green" />执行引擎</div>
          <div className="engine-item"><span className="eng-dot c-green" />验证循环</div>
          <div className="engine-item"><span className="eng-dot c-green" />自愈机制</div>
          <div className="engine-item"><span className="eng-dot c-green" />证据追踪</div>
        </div>
        {stats && stats.last_completed && (
          <div className="engine-last">最近完成: {stats.last_completed}</div>
        )}
      </div>
    </div>
  );
}
