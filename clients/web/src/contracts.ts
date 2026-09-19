export interface Identity {
  id: string;
  username: string;
}
export interface Holding {
  id: string;
  program_key: string;
  tier_key: string;
  program_display_name: string;
  tier_display_name: string;
  valid_until: string | null;
}
export interface CatalogNode {
  id: string;
  program_key: string;
  tier_key: string;
  program: string;
  tier: string;
}
export interface Activity {
  ref: string;
  version_ref: string;
  name: string;
  is_current: boolean;
  updated_at: string;
  card: { summary: string; lifecycle_status: string };
}
export interface Step {
  mapping_status?: "UNCONFIRMED";
  uncertainty_note?: string;
  target_program_name?: string;
  possible_target_tiers?: string[];
  ref: string;
  from: string;
  to: string;
  from_tier_id?: string;
  to_tier_id?: string;
  activity_ref: string;
  version_ref: string;
  paid?: boolean | null;
  cost?: { paid?: boolean | null };
}
export interface Route {
  from: string;
  to: string;
  step_refs: string[];
  steps: Record<string, Step>;
  paid?: boolean | null;
  step_count: number;
}
export interface DisplayObject {
  ref: string;
  data: Route & Record<string, any>;
}
export interface Block {
  type: string;
  title?: string;
  reason?: string;
  columns?: string[];
  roles?: { ref: string; role: string }[];
  payload: { objects: DisplayObject[]; research?: DisplayObject[] };
}
export interface Presentation {
  answer?: string;
  blocks: Block[];
  next_steps?: { label: string; message: string; subject_refs: string[] }[];
}
export interface Message {
  id: string;
  role: string;
  content: { type: string; text?: string; ref?: string }[];
  attachments?: {
    presentation_refs?: string[];
    operations?: { summary: string }[];
  };
  metadata?: { interrupted?: boolean; progress_only?: boolean };
}
export interface Run {
  run_id: string;
  status: string;
  last_seq: number;
}
export interface Workspace {
  id: string;
  revision: number;
  messages: Message[];
  runs: Run[];
  next_cursor?: string;
}
export const terminal = (s: string) =>
  ["COMPLETED", "PARTIAL", "CANCELED", "FAILED"].includes(s);
