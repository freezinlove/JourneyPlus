import {describe, expect, it} from "vitest";
import {visibleMessages, markProgress} from "./chatMessages";
import type {Message} from "./contracts";
const user:Message={id:"u",role:"user",content:[{type:"text",text:"能匹配到啥"}]};
const progress:Message={id:"p",role:"assistant",content:[{type:"text",text:"正在查"},{type:"tool_call"}]};
const final:Message={id:"f",role:"assistant",content:[{type:"text",text:"查到这些路径"}]};
describe("turn narration",()=>{
  it("shows current progress but removes it once final text starts",()=>{
    expect(visibleMessages([user,progress],true)[1].content[0].text).toBe("正在查");
    expect(visibleMessages([user,progress,final],true)[1].content.some(p=>p.type==="text")).toBe(false);
  });
  it("retains final text, graphs and operation receipts after completion and reload",()=>{
    const withGraph={...progress,attachments:{presentation_refs:["artifact:1"],operations:[{summary:"保存成功"}]}};
    const result=visibleMessages([user,withGraph,final],false);
    expect(result[1].attachments).toEqual(withGraph.attachments);
    expect(result[1].content.some(p=>p.type==="text")).toBe(false);
    expect(result[2]).toEqual(final);
  });
  it("marks streamed narration only in the current turn",()=>{
    expect(markProgress([final,user])[0]).toEqual(final);
    const streamed={...final,id:"live"};
    const result=markProgress([user,streamed]);
    expect(visibleMessages(result,false)[1].content).toEqual([]);
    expect(streamed.metadata).toBeUndefined();
  });
});
