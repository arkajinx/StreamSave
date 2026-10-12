"use strict";

const $ = (id) => document.getElementById(id);
const form = $("link-form");
const input = $("video-url");
const prepareButton = $("download-button");
const authorization = $("authorized");
const state = { preview: null, kind: "video", selected: null, jobId: null, polling: null, expiryTimer: null, busy: false, checking: false, version: 0 };

function showError(id, message) { const el = $(id); el.textContent = message || ""; el.hidden = !message; }
function duration(seconds) {
  const n = Math.floor(Number(seconds) || 0);
  return n >= 3600 ? `${Math.floor(n / 3600)}:${String(Math.floor(n % 3600 / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}` : `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
}
function bytes(value) {
  const n = Number(value);
  if (!n) return "Size varies";
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} GB` : n >= 1024 ** 2 ? `${(n / 1024 ** 2).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}
async function api(path, options = {}, timeout = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, { ...options, credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(body.detail) ? body.detail.map((x) => x.msg).join(". ") : body.detail;
      throw new Error(typeof detail === "string" ? detail : "The server could not complete this request. Try again.");
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Please try again.");
    if (error instanceof TypeError) throw new Error("Could not reach the server. Check your connection and try again.");
    throw error;
  } finally { clearTimeout(timer); }
}
function step(current) {
  ["step-link", "step-format", "step-save"].forEach((id, index) => {
    $(id).classList.toggle("current", index === current);
    $(id).classList.toggle("done", index < current);
  });
}
function setChecking(checking) {
  state.checking = checking;
  $("checking").hidden = !checking;
  $("check-button").disabled = checking || state.busy;
  $("check-button").querySelector(".spinner").hidden = !checking;
  $("check-label").textContent = checking ? "Checking…" : "Check link";
  form.setAttribute("aria-busy", String(checking));
}
function updatePrepare() { prepareButton.disabled = state.busy || !state.selected || !authorization.checked; }
function renderFormats(kind) {
  state.kind = kind;
  const options = state.preview.options.filter((x) => x.kind === kind);
  state.selected = options[0]?.id || null;
  $("tab-video").classList.toggle("active", kind === "video");
  $("tab-audio").classList.toggle("active", kind === "audio");
  $("tab-video").setAttribute("aria-selected", String(kind === "video"));
  $("tab-audio").setAttribute("aria-selected", String(kind === "audio"));
  $("tab-video").tabIndex = kind === "video" ? 0 : -1;
  $("tab-audio").tabIndex = kind === "audio" ? 0 : -1;
  $("formats-panel").setAttribute("aria-labelledby", `tab-${kind}`);
  $("audio-note").hidden = kind !== "audio";
  $("video-note").hidden = kind !== "video";
  const grid = $("format-options");
  grid.replaceChildren();
  const legend = document.createElement("legend"); legend.className = "sr-only"; legend.textContent = "Choose an output format"; grid.append(legend);
  if (!options.length) {
    const message = document.createElement("p"); message.className = "formats-empty"; message.textContent = `No supported ${kind} formats are available for this video.`; grid.append(message);
  }
  options.forEach((option, index) => {
    const label = document.createElement("label"); label.className = "format-card"; label.classList.toggle("selected", index === 0);
    const radio = document.createElement("input"); radio.type = "radio"; radio.name = "format"; radio.value = option.id; radio.checked = index === 0;
    const quality = document.createElement("span"); quality.className = "format-quality"; quality.textContent = option.height ? (option.label || `Up to ${option.height}p`) : option.bitrate ? `${option.bitrate} kbps` : "Original";
    const type = document.createElement("span"); type.className = "format-container"; type.textContent = option.container.toUpperCase();
    const size = document.createElement("span"); size.className = "format-size"; size.textContent = option.estimated_bytes ? `≈ ${bytes(option.estimated_bytes)}` : "Size varies";
    radio.addEventListener("change", () => {
      state.selected = option.id;
      grid.querySelectorAll(".format-card").forEach((el) => el.classList.toggle("selected", el.querySelector("input").checked));
      updatePrepare();
    });
    label.append(radio, quality, type, size); grid.append(label);
  });
  updatePrepare();
}
function setBusy(value) {
  state.busy = value;
  input.disabled = value;
  $("paste-button").disabled = value;
  $("check-button").disabled = value || state.checking;
  $("tab-video").disabled = value;
  $("tab-audio").disabled = value;
  authorization.disabled = value;
  $("format-options").querySelectorAll("input").forEach((el) => { el.disabled = value; });
  updatePrepare();
}
function clearPolls() { clearTimeout(state.polling); clearInterval(state.expiryTimer); }
function rememberJob(id) { try { if (id) sessionStorage.setItem("streamsave_job", id); else sessionStorage.removeItem("streamsave_job"); } catch {} }

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || state.checking) return;
  const url = input.value.trim();
  if (!url) { showError("link-error", "Paste a YouTube video link first."); input.focus(); return; }
  const version = ++state.version;
  clearPolls(); rememberJob(null); state.jobId = null;
  showError("link-error", ""); showError("selection-error", "");
  $("results").hidden = true; $("job-panel").hidden = true;
  state.preview = null; state.selected = null; authorization.checked = false;
  setChecking(true); step(0);
  try {
    const preview = await api("/api/inspect", { method: "POST", body: JSON.stringify({ url }) }, 65000);
    if (version !== state.version) return;
    state.preview = preview;
    $("video-title").textContent = preview.title;
    $("video-channel").textContent = preview.channel || "YouTube video";
    $("video-duration").textContent = duration(preview.duration);
    $("video-duration").hidden = !preview.duration;
    $("video-thumbnail").src = preview.thumbnail;
    $("video-thumbnail").alt = `Thumbnail for ${preview.title}`;
    $("video-count").textContent = preview.options.filter((x) => x.kind === "video").length;
    $("audio-count").textContent = preview.options.filter((x) => x.kind === "audio").length;
    renderFormats(preview.options.some((x) => x.kind === "video") ? "video" : "audio");
    $("results").hidden = false; step(1);
  } catch (error) { if (version === state.version) showError("link-error", error.message); }
  finally { if (version === state.version) setChecking(false); }
});
$("paste-button").addEventListener("click", async () => {
  try { input.value = await navigator.clipboard.readText(); input.dispatchEvent(new Event("input")); input.focus(); }
  catch { showError("link-error", "Paste your link with Ctrl+V or ⌘V."); input.focus(); }
});
input.addEventListener("input", () => {
  if (state.checking) {
    // Ignore an old link's response if the user edits the field mid-request.
    state.version++;
    setChecking(false);
  }
  if (state.preview && !state.busy) {
    state.preview = null; state.selected = null; authorization.checked = false;
    $("results").hidden = true; updatePrepare(); step(0);
  }
  showError("link-error", "");
});
authorization.addEventListener("change", updatePrepare);
$("tab-video").addEventListener("click", () => { if (state.preview && !state.busy) renderFormats("video"); });
$("tab-audio").addEventListener("click", () => { if (state.preview && !state.busy) renderFormats("audio"); });
for (const id of ["tab-video", "tab-audio"]) {
  $(id).addEventListener("keydown", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) && !state.busy && state.preview) {
      event.preventDefault();
      const kind = event.key === "Home" ? "video" : event.key === "End" ? "audio" : state.kind === "video" ? "audio" : "video";
      renderFormats(kind); $(`tab-${kind}`).focus();
    }
  });
}

prepareButton.addEventListener("click", async () => {
  if (!state.preview || !state.selected || state.busy || !authorization.checked) return;
  showError("selection-error", ""); setBusy(true);
  prepareButton.textContent = "Starting…";
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify({ inspection_id: state.preview.inspection_id, option_id: state.selected, authorized: authorization.checked }) });
    state.jobId = job.id; rememberJob(job.id);
    $("results").hidden = true; $("job-panel").hidden = false; step(2);
    renderJob(job); pollJob(job.id);
    $("job-heading").tabIndex = -1; $("job-heading").focus({ preventScroll: true });
  } catch (error) { showError("selection-error", error.message); setBusy(false); }
  finally { prepareButton.textContent = "Prepare download"; }
});

function renderJob(job) {
  $("job-title").textContent = job.title;
  $("job-stage").textContent = job.stage;
  $("job-percentage").textContent = `${Math.round(job.progress)}%`;
  $("job-progress").value = job.progress;
  $("job-info").textContent = job.speed ? `${bytes(job.speed)}/s${job.eta ? ` · About ${duration(job.eta)} remaining for this stream` : ""}` : "";
  showError("job-error", job.error);
  $("save-button").hidden = job.status !== "ready";
  $("reset-button").hidden = !["ready", "failed", "cancelled"].includes(job.status);
  $("cancel-button").hidden = ["ready", "failed", "cancelled"].includes(job.status);
  $("cancel-button").disabled = job.status === "cancelling";
  $("expiry-note").hidden = job.status !== "ready";
  $("job-heading").textContent = job.status === "ready" ? "Your file is ready" : job.status === "failed" ? "Download couldn't finish" : job.status === "cancelled" ? "Download cancelled" : "Preparing your file";
  if (job.status === "ready") {
    $("save-button").href = job.file_url; $("save-button").textContent = `Save ${job.container.toUpperCase()}`;
    $("save-button").removeAttribute("aria-disabled");
    $("job-info").textContent = `${bytes(job.size)} · ${job.container.toUpperCase()}`;
    const deadline = Date.now() + (job.expires_in || 0) * 1000;
    clearInterval(state.expiryTimer);
    const countdown = () => {
      const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));
      $("expiry-note").textContent = remaining ? `Temporary file expires in ${duration(remaining)}.` : "This temporary file expired. Start again to prepare a new copy.";
      if (!remaining) { $("save-button").removeAttribute("href"); $("save-button").setAttribute("aria-disabled", "true"); clearInterval(state.expiryTimer); }
    };
    countdown(); state.expiryTimer = setInterval(countdown, 1000);
  }
}
async function pollJob(id, failures = 0) {
  if (state.jobId !== id) return;
  try {
    const job = await api(`/api/jobs/${id}`);
    if (state.jobId !== id) return;
    renderJob(job);
    if (["ready", "failed", "cancelled"].includes(job.status)) return;
    state.polling = setTimeout(() => pollJob(id), 1200);
  } catch (error) {
    if (state.jobId !== id) return;
    if (failures < 3) {
      $("job-info").textContent = "Connection interrupted. Reconnecting…";
      state.polling = setTimeout(() => pollJob(id, failures + 1), 2500);
    } else {
      showError("job-error", `${error.message} Refresh this page to check the download again.`);
      $("reset-button").hidden = false;
      $("cancel-button").hidden = true;
    }
  }
}
$("cancel-button").addEventListener("click", async () => {
  if (!state.jobId) return;
  $("cancel-button").disabled = true;
  try { const job = await api(`/api/jobs/${state.jobId}`, { method: "DELETE" }); renderJob(job); }
  catch (error) { showError("job-error", error.message); $("cancel-button").disabled = false; }
});
$("reset-button").addEventListener("click", async () => {
  const id = state.jobId;
  $("reset-button").disabled = true;
  try {
    // Free this job's queue/storage slot before starting another.
    if (id) await api(`/api/jobs/${id}`, { method: "DELETE" }).catch(() => {});
    state.version++; state.jobId = null; rememberJob(null); clearPolls(); setBusy(false);
    $("job-panel").hidden = true; $("save-button").hidden = true; showError("job-error", "");
    if (state.preview) { $("results").hidden = false; step(1); } else { step(0); }
    input.focus();
  } finally { $("reset-button").disabled = false; }
});
$("save-button").addEventListener("click", (event) => {
  if ($("save-button").getAttribute("aria-disabled") === "true") event.preventDefault();
});

(async () => {
  try {
    const settings = await api("/api/config");
    $("limits").textContent = `Up to ${Math.ceil(settings.max_duration_seconds / 60)} min · ${settings.max_file_mb} MB`;
    await api("/api/health");
  } catch (error) { const notice = $("server-notice"); notice.textContent = error.message; notice.hidden = false; }
  let saved = null; try { saved = sessionStorage.getItem("streamsave_job"); } catch {}
  if (saved && /^[a-f0-9]{32}$/.test(saved)) {
    state.jobId = saved; setBusy(true); step(2); $("job-panel").hidden = false;
    await pollJob(saved);
  }
})();
