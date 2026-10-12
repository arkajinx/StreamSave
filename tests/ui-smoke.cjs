/* DOM behavior checks, not a visual/browser layout test.
   Optional: npm install --no-save --prefix /tmp/streamsave-ui jsdom
   STREAMSAVE_JSDOM=/tmp/streamsave-ui/node_modules/jsdom node tests/ui-smoke.cjs
*/
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require(process.env.STREAMSAVE_JSDOM || "jsdom");
const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const answer = (body, ok = true) => ({ ok, json: async () => body });
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
const preview = { inspection_id: "a".repeat(32), title: "Owned fixture <script>", channel: "Test channel", duration: null, options_are_presets: true, thumbnail: "https://i.ytimg.com/vi/BaW_jenozKc/hqdefault.jpg", options: [
  { id: "mp4-360", kind: "video", container: "mp4", height: 360, label: "Up to 360p", estimated_bytes: null },
  { id: "mp3-256", kind: "audio", container: "mp3", bitrate: 256, estimated_bytes: null },
] };
function setup(inspectHandler) {
  const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  const calls = [];
  w.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/api/config") return answer({ max_duration_seconds: 3600, max_file_mb: 500 });
    if (url === "/api/health") return answer({ status: "ok" });
    if (url === "/api/inspect") return inspectHandler(url, options);
    if (url === "/api/jobs" && options.method === "POST") return answer({ id: "b".repeat(32), title: preview.title, status: "queued", stage: "Queued", progress: 0 });
    if (url.startsWith("/api/jobs/")) return answer({ id: "b".repeat(32), title: preview.title, status: "ready", stage: "Ready to save", progress: 100, container: "mp3", size: 500, expires_in: 600, file_url: `/api/jobs/${"b".repeat(32)}/file` });
    throw new Error("Unexpected request: " + url);
  };
  w.eval(source);
  return { dom, w, calls, $: (id) => w.document.getElementById(id) };
}
function submit(env, value) {
  env.$("video-url").value = value;
  env.$("link-form").dispatchEvent(new env.w.Event("submit", { bubbles: true, cancelable: true }));
}
async function staleInspection() {
  let resolve;
  const env = setup(() => new Promise((r) => { resolve = r; }));
  try {
    await settle();
    submit(env, "https://youtu.be/BaW_jenozKc");
    await settle();
    env.$("video-url").value = "https://youtu.be/aaaaaaaaaaa";
    env.$("video-url").dispatchEvent(new env.w.Event("input", { bubbles: true }));
    resolve(answer(preview));
    await settle();
    assert.equal(env.$("results").hidden, true, "Editing the link must invalidate the pending video's preview");
    assert.equal(env.$("check-button").disabled, false, "The new link can be checked");
  } finally { env.dom.window.close(); }
}
async function happyPath() {
  const env = setup(async () => answer(preview));
  try {
    await settle(); submit(env, "https://youtu.be/BaW_jenozKc"); await settle();
    assert.equal(env.$("results").hidden, false);
    assert.equal(env.$("video-title").textContent, preview.title, "Remote titles remain text");
    assert.equal(env.$("video-duration").hidden, true, "Unknown duration is hidden");
    assert.match(env.$("format-options").textContent, /Up to 360p/, "Quality is an export cap");
    assert.equal(env.$("download-button").disabled, true, "Authorization is required");
    env.$("tab-audio").click();
    assert.equal(env.$("tab-audio").getAttribute("aria-selected"), "true");
    assert.match(env.$("format-options").textContent, /256 kbps/);
    env.$("authorized").checked = true;
    env.$("authorized").dispatchEvent(new env.w.Event("change"));
    assert.equal(env.$("download-button").disabled, false);
    env.$("download-button").click(); await settle(); await settle();
    assert.equal(env.$("save-button").hidden, false);
    assert.equal(env.$("save-button").textContent, "Save MP3");
    assert.equal(env.$("job-heading").textContent, "Your file is ready");
    const submitted = JSON.parse(env.calls.find((x) => x.url === "/api/jobs").options.body);
    assert.equal(submitted.option_id, "mp3-256");
    assert.equal(submitted.authorized, true);
  } finally { env.dom.window.close(); }
}
async function upstreamError() {
  const env = setup(async () => answer({ detail: "YouTube refused this request." }, false));
  try {
    await settle(); submit(env, "https://youtu.be/BaW_jenozKc"); await settle();
    assert.equal(env.$("results").hidden, true);
    assert.equal(env.$("link-error").textContent, "YouTube refused this request.");
    assert.equal(env.$("check-button").disabled, false);
  } finally { env.dom.window.close(); }
}
(async () => {
  await staleInspection();
  await happyPath();
  await upstreamError();
  console.log("3 DOM checks passed: stale-link response, video/audio job flow, upstream error");
})().catch((error) => { console.error(error); process.exitCode = 1; });
