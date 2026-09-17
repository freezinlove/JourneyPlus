import { describe, it, expect } from "vitest";
import { layout } from "./Graph";
import type { Route, Step } from "./contracts";
const step = (ref: string, from: string, to: string): Step => ({
  ref,
  from,
  to,
  from_tier_id: from,
  to_tier_id: to,
  activity_ref: "activity",
  version_ref: ref,
});
const route = (steps: Step[]): Route => ({
  from: steps[0].from,
  to: steps.at(-1)!.to,
  step_count: steps.length,
  step_refs: steps.map((s) => s.ref),
  steps: Object.fromEntries(steps.map((s) => [s.ref, s])),
});
describe("server-selected path projection", () => {
  it("keeps branches, intermediate nodes, alternative version refs without inventing edges", () => {
    const a = step("one", "A", "B"),
      b = step("two", "B", "C"),
      c = step("three", "A", "D"),
      d = step("four", "D", "C");
    const g = layout([route([a, b]), route([c, d])]);
    expect(g.nodes.map((n) => n.id)).toEqual(["A", "B", "C", "D"]);
    expect(g.edges.map((e) => e.step.version_ref)).toEqual([
      "one",
      "two",
      "three",
      "four",
    ]);
    expect(g.nodes.find((n) => n.id === "C")?.steps).toHaveLength(2);
  });
  it("retains multiple actual origins", () => {
    const g = layout([
      route([step("one", "A", "C")]),
      route([step("two", "B", "C")]),
    ]);
    expect(g.nodes.filter((n) => !n.steps.length).map((n) => n.id)).toEqual([
      "A",
      "B",
    ]);
  });
});
