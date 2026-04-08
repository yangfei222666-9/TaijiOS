const API_BASE = "/api";

export interface TaskSubmitResponse {
  task_id: string;
  status: string;
  created_at: string;
}

export interface TaskStatus {
  task_id: string;
  status: string;
  phase: string;
  attempts: number;
  score: number;
  self_healed: boolean;
  reason_code: string;
  created_at: string;
  updated_at: string;
}

export interface TaskEvidence {
  task_id: string;
  trace: {
    task_id: string;
    status: string;
    started_at: number;
    ended_at: number;
    steps: Array<{
      name: string;
      status: string;
      started_at: number;
      ended_at: number;
      output: Record<string, unknown> | null;
      error: Record<string, unknown> | null;
    }>;
  };
  evidence: {
    succeeded: number;
    self_healed: boolean;
    final_score: number;
    attempts: number;
    reason_code: string;
  };
  events: Array<{ ts: number; type: string; data: Record<string, unknown> }>;
}

export async function submitTask(message: string, maxRetries = 2): Promise<TaskSubmitResponse> {
  const res = await fetch(`${API_BASE}/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, max_retries: maxRetries }),
  });
  if (!res.ok) throw new Error(`Submit failed: ${res.status}`);
  return res.json();
}

export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const res = await fetch(`${API_BASE}/v1/tasks/${taskId}`);
  if (!res.ok) throw new Error(`Status failed: ${res.status}`);
  return res.json();
}

export async function getTaskEvidence(taskId: string): Promise<TaskEvidence> {
  const res = await fetch(`${API_BASE}/v1/tasks/${taskId}/evidence`);
  if (!res.ok) throw new Error(`Evidence failed: ${res.status}`);
  return res.json();
}

export interface StreamEvent {
  timestamp: number;
  type: string;
  [key: string]: unknown;
}

export function streamTask(
  taskId: string,
  onEvent: (evt: StreamEvent) => void,
  onDone: () => void,
  onError: (err: Error) => void,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/tasks/${taskId}/stream`, {
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        onError(new Error(`Stream failed: ${res.status}`));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;
          const payload = trimmed.slice(6);
          if (payload === "[DONE]") {
            onDone();
            return;
          }
          try {
            onEvent(JSON.parse(payload));
          } catch { /* skip malformed */ }
        }
      }
      onDone();
    } catch (err) {
      if (!controller.signal.aborted) {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    }
  })();

  return () => controller.abort();
}
