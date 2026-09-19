import type { Message } from "./contracts";

function lastIndex(messages: Message[], predicate: (m: Message) => boolean): number {
  for (let i = messages.length - 1; i >= 0; i--) if (predicate(messages[i])) return i;
  return -1;
}

/** Hide transient narration after a turn, retaining presentations and receipts. */
export function visibleMessages(messages: Message[], busy: boolean): Message[] {
  const lastUser = lastIndex(messages, m => m.role === "user");
  const lastText = lastIndex(messages, m => m.role === "assistant" && m.content.some(p => p.type === "text" && p.text?.trim()));
  return messages.map((m, index) => {
    const process = m.metadata?.progress_only || m.content.some(p => p.type === "tool_call");
    return process && !(busy && index > lastUser && index === lastText)
      ? { ...m, content: m.content.filter(p => p.type !== "text") } : m;
  });
}

export function markProgress(messages: Message[]): Message[] {
  const lastUser = lastIndex(messages, m => m.role === "user");
  const index = lastIndex(messages, m => m.role === "assistant" && m.content.some(p => p.type === "text"));
  return index > lastUser ? messages.map((m, i) => i === index
    ? { ...m, metadata: { ...m.metadata, progress_only: true } } : m) : messages;
}
