const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const viewer = vm.createContext({ fetch: () => new Promise(() => {}), document: { addEventListener() {} } });
vm.runInContext(readFileSync(join(__dirname, "../harness/viewer/app.js"), "utf8"), viewer);

test("episode totals include reasoning without adding it twice", () => {
  const call = { usage: { prompt_tokens: 10, completion_tokens: 20, total_tokens: 30, completion_tokens_details: { reasoning_tokens: 15 } } };
  const episode = { transitions: [call, call].map((llm) => ({ action: { metadata: { llm } } })) };
  const totals = viewer.episodeUsage(episode);
  assert.equal(totals.reasoning_tokens, 30);
  assert.equal(totals.output_tokens, 40);
  assert.equal(totals.total_tokens, 60);
});

test("missing reasoning differs from a reported zero and partial totals are labeled", () => {
  assert.equal(viewer.tokenUsage({}).reasoning_tokens, "Not reported");
  assert.equal(viewer.tokenUsage({ usage: { completion_tokens_details: { reasoning_tokens: 0 } } }).reasoning_tokens, 0);
  const episode = { transitions: [
    { action: { metadata: { llm: { usage: { completion_tokens_details: { reasoning_tokens: 7 } } } } } },
    { action: { metadata: { llm: { usage: {} } } } }
  ] };
  assert.equal(viewer.episodeUsage(episode).reasoning_tokens, "7 (1/2 calls reported)");
  assert.match(viewer.metricGrid(viewer.episodeUsage(episode)), /7 \(1\/2 calls reported\)/);
});

test("model panel shows counts, escaped reasoning, and raw output", () => {
  const transition = { action: { kind: "DONE", metadata: { llm: {
    usage: { completion_tokens_details: { reasoning_tokens: 42 } },
    reasoning_content: "<script>reasoning</script>",
    assistant_content: "raw response"
  } } } };
  const html = viewer.facetDetails("Control", transition, 0);
  assert.match(html, /Reasoning Tokens/);
  assert.match(html, /42/);
  assert.match(html, /&lt;script&gt;reasoning&lt;\/script&gt;/);
  assert.match(html, /raw response/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(viewer.reasoningView({ thinking_blocks: [{ type: "thinking", thinking: "Returned summary" }] }), /Returned summary/);
});

test("agent input distinguishes sent content from other captured observations", () => {
  const transition = {
    observation: { visual: { artifact: "screenshot.png" } },
    action: { metadata: { llm: {
      observation_modalities: ["pruned_html"],
      messages: [{ role: "system", content: "Instructions" }, { role: "user", content: "<button bid=0>Buy</button>" }]
    } } }
  };
  assert.equal(viewer.agentModality(transition), "Pruned Html");
  const html = viewer.agentInput({ index: 0 }, transition);
  assert.match(html, /&lt;button bid=0&gt;Buy&lt;\/button&gt;/);
  assert.doesNotMatch(html, /<img/);
  transition.action.metadata.llm.observation_modalities = ["screenshot"];
  transition.action.metadata.llm.messages[1].content = [{ type: "text", text: "Step 0" }, { type: "image_url", image_url: { artifact: "observation.visual" } }];
  assert.match(viewer.agentInput({ index: 0 }, transition), /<img src="\/artifact\/0\/screenshot.png"/);
  delete transition.action.metadata.llm.observation_modalities;
  assert.match(viewer.agentModality(transition), /legacy/);
});
