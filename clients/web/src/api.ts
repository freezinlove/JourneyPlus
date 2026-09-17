export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
  signal?: AbortSignal,
): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = r.status === 204 ? null : await r.json();
  if (!r.ok) {
    const code = data?.code || data?.detail?.code || "";
    if (r.status === 401 && !["/auth/me", "/auth/login"].includes(path))
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      r.status,
      code,
      data?.message ||
        (
          {
            LOGIN_REQUIRED: "请登录后继续",
            WORKSPACE_EXPIRED: "当前对话已过期，请开启新对话",
            AGENT_MODEL_UNAVAILABLE: "模型暂不可用，新闻与会籍仍可使用",
            AGENT_UNAVAILABLE: "Agent 暂不可用",
            DATABASE_UNAVAILABLE: "数据库暂不可用",
            REVISION_CONFLICT: "对话已更新，请重试",
          } as Record<string, string>
        )[code] ||
        (typeof data?.detail === "string"
          ? data.detail
          : "请求未完成，请稍后重试"),
    );
  }
  return data;
}
export function safeUrl(value: string): string | undefined {
  try {
    const u = new URL(value, location.origin);
    return ["http:", "https:"].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
}
export function readable(v: any): string {
  if (v == null) return "未提供";
  if (typeof v !== "object") return String(v);
  if (Array.isArray(v)) return v.map(readable).join("；");
  if ("value" in v) return readable(v.value);
  if (v.raw_text) return v.raw_text;
  if (v.items)
    return (
      v.items
        .map((i: any) => i.raw_text || i.reason || readable(i))
        .join("；") || "未记录"
    );
  return Object.entries(v)
    .filter(([k]) => !/(?:_id|_ref|evidence|schema)/.test(k))
    .map(([k, x]) => `${k}：${readable(x)}`)
    .join("；");
}
