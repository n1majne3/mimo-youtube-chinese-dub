const state = {
  jobId: null,
  pollTimer: null,
  classification: null,
  config: null,
};

const $ = (id) => document.getElementById(id);

const CONTENT_LABELS = {
  auto: "自动判断",
  solo: "单人讲解",
  interview: "访谈",
  narration: "旁白",
  "multi-speaker": "多人内容",
  music: "音乐",
  unknown: "不确定",
};

const MODE_LABELS = {
  auto: "自动判断",
  single: "单人",
  "two-speaker": "双人",
};

const VOICE_LABELS = {
  auto: "自动判断",
  "voice-clone": "声音克隆",
  "voice-design": "声音设计",
};

const STATUS_LABELS = {
  idle: "空闲",
  queued: "排队中",
  running: "运行中",
  complete: "完成",
  failed: "失败",
  error: "错误",
};

const API_PROFILE_LABELS = {
  token_plan: "Token Plan",
  payg: "按量 API",
};

function selectedScope() {
  return document.querySelector("input[name='scope']:checked")?.value || "test";
}

function selectedApiSource() {
  return document.querySelector("input[name='api_key_source']:checked")?.value || "env";
}

function setApiSource(source) {
  const radio = document.querySelector(`input[name='api_key_source'][value='${source}']`);
  if (radio) radio.checked = true;
}

function formPayload() {
  const form = new FormData($("jobForm"));
  const payload = {};
  for (const [key, value] of form.entries()) {
    if (value !== "") payload[key] = value;
  }
  payload.dry_run = $("dryRun").checked;
  payload.voice_clone_confirmed = $("consent").checked;
  if (payload.scope === "full") {
    delete payload.clip_start;
    delete payload.clip_duration;
  }
  if (payload.content_type && payload.content_type !== "auto") {
    if (payload.mode === "auto") payload.mode = defaultModeForContentType(payload.content_type);
    if (payload.voice_strategy === "auto") {
      payload.voice_strategy = defaultVoiceStrategyForContentType(payload.content_type);
    }
  }
  return payload;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setBusy(button, busy) {
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? button.dataset.busyLabel || "处理中" : button.dataset.label;
}

function defaultModeForContentType(contentType) {
  return contentType === "interview" ? "two-speaker" : "single";
}

function defaultVoiceStrategyForContentType(contentType) {
  return contentType === "narration" || contentType === "music" ? "voice-design" : "voice-clone";
}

function effectiveMode() {
  const selected = $("mode").value;
  if (selected !== "auto") return selected;
  if ($("contentType").value !== "auto") return defaultModeForContentType($("contentType").value);
  if (state.classification?.recommended_mode) return state.classification.recommended_mode;
  return defaultModeForContentType($("contentType").value);
}

function effectiveVoiceStrategy() {
  const selected = $("voiceStrategy").value;
  if (selected !== "auto") return selected;
  if ($("contentType").value !== "auto") return defaultVoiceStrategyForContentType($("contentType").value);
  if (state.classification?.recommended_voice_strategy) return state.classification.recommended_voice_strategy;
  return defaultVoiceStrategyForContentType($("contentType").value);
}

function setPanelVisible(panel, visible) {
  panel.classList.toggle("is-hidden", !visible);
  for (const control of panel.querySelectorAll("input, select, textarea")) {
    control.disabled = !visible;
  }
}

function syncVoiceFields() {
  const mode = effectiveMode();
  const voiceStrategy = effectiveVoiceStrategy();
  const isTwoSpeaker = mode === "two-speaker";
  const usesClone = isTwoSpeaker || voiceStrategy === "voice-clone";
  const consent = $("consent");

  for (const panel of document.querySelectorAll("[data-voice-panel]")) {
    const role = panel.dataset.voicePanel;
    setPanelVisible(
      panel,
      (role === "single-clone" && !isTwoSpeaker && voiceStrategy === "voice-clone") ||
        (role === "two-speaker" && isTwoSpeaker) ||
        (role === "clone-consent" && usesClone),
    );
  }

  for (const panel of document.querySelectorAll("[data-timing-panel]")) {
    const role = panel.dataset.timingPanel;
    setPanelVisible(panel, (role === "single" && !isTwoSpeaker) || (role === "two-speaker" && isTwoSpeaker));
  }

  consent.required = usesClone && !$("dryRun").checked;
}

function syncApiFields() {
  const isManual = selectedApiSource() === "manual";
  for (const panel of document.querySelectorAll("[data-api-panel='manual']")) {
    setPanelVisible(panel, isManual);
  }
  $("apiKey").required = isManual && !$("dryRun").checked;
  if (isManual) {
    const profileLabel = API_PROFILE_LABELS[$("apiProfile").value] || $("apiProfile").value;
    if ($("apiKey").value.trim() || $("dryRun").checked) {
      $("keyState").textContent = `临时输入: ${profileLabel}`;
      $("keyState").classList.remove("is-warm", "is-error");
    } else {
      $("keyState").textContent = `请输入 ${profileLabel} key`;
      $("keyState").classList.add("is-warm");
    }
  } else if (state.config) {
    renderApiState(state.config);
  }
}

function renderApiState(config) {
  state.config = config;
  const api = config.api || {};
  if (api.key_set) {
    const sourceLabel = api.source === "manual" ? "临时输入" : ".env";
    const profileLabel = API_PROFILE_LABELS[api.profile] || api.profile || "未知";
    $("keyState").textContent = `${sourceLabel}: ${profileLabel}`;
    $("keyState").classList.remove("is-warm", "is-error");
  } else {
    $("keyState").textContent = ".env 未检测到 API key";
    $("keyState").classList.add("is-warm");
  }
}

function renderAnalysis(data) {
  const classification = data.classification || {};
  state.classification = classification;
  $("analysisBadge").textContent = "完成";
  $("analysisBadge").classList.remove("is-error");
  $("detectedType").textContent = CONTENT_LABELS[classification.content_type] || classification.content_type || "-";
  $("detectedMode").textContent =
    MODE_LABELS[classification.recommended_mode] || classification.recommended_mode || "-";
  $("detectedVoice").textContent =
    VOICE_LABELS[classification.recommended_voice_strategy] || classification.recommended_voice_strategy || "-";
  $("detectedConfidence").textContent =
    typeof classification.confidence === "number" ? classification.confidence.toFixed(2) : "-";
  $("detectedReason").textContent = classification.reason || "";
  if (data.job_dir && !$("jobDir").value) $("jobDir").value = data.job_dir;
  if (classification.recommended_mode === "two-speaker") $("advancedSettings").open = true;
  syncVoiceFields();
}

function versionedUrl(url, version) {
  if (!url) return "";
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}t=${encodeURIComponent(version || Date.now())}`;
}

function setLink(id, url, version) {
  const link = $(id);
  if (!url) {
    link.removeAttribute("href");
    link.classList.add("is-hidden");
    return false;
  }
  link.href = versionedUrl(url, version);
  link.classList.remove("is-hidden");
  return true;
}

function syncVideoTrack(video, url, version) {
  const trackUrl = versionedUrl(url, version);
  if (video.dataset.trackSrc === trackUrl) return;
  for (const track of video.querySelectorAll("track[data-generated='subtitle']")) {
    track.remove();
  }
  video.dataset.trackSrc = trackUrl;
  if (!trackUrl) return;
  const track = document.createElement("track");
  track.dataset.generated = "subtitle";
  track.kind = "subtitles";
  track.label = "中文";
  track.srclang = "zh-CN";
  track.src = trackUrl;
  track.default = true;
  video.appendChild(track);
}

function syncResultLinks(data) {
  const hasVideo = setLink("videoLink", data.video_url, data.video_mtime);
  const hasSrt = setLink("srtLink", data.subtitle_srt_url, data.subtitle_mtime);
  const hasVtt = setLink("vttLink", data.subtitle_vtt_url, data.subtitle_mtime);
  $("resultLinks").classList.toggle("is-hidden", !(hasVideo || hasSrt || hasVtt));
}

function renderStatus(data) {
  $("runState").textContent = STATUS_LABELS[data.status] || data.status || "未知";
  $("jobId").textContent = `任务: ${data.job_id || "-"}`;
  $("jobDir").textContent = `目录: ${data.job_dir || "-"}`;
  $("outputPath").textContent = `输出: ${data.output || "-"}`;
  $("logTail").textContent = data.log_tail || "";
  $("logTail").classList.toggle("is-hidden", !data.log_tail);

  const video = $("videoPreview");
  if (data.video_url) {
    const videoUrl = versionedUrl(data.video_url, data.video_mtime);
    if (video.dataset.src !== videoUrl) {
      video.src = videoUrl;
      video.dataset.src = videoUrl;
    }
    video.style.display = "block";
    syncVideoTrack(video, data.subtitle_vtt_url, data.subtitle_mtime);
  } else {
    video.removeAttribute("src");
    delete video.dataset.src;
    video.style.display = "none";
    syncVideoTrack(video, null);
  }
  syncResultLinks(data);

  if (data.status === "complete" || data.status === "failed") {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollStatus() {
  if (!state.jobId) return;
  try {
    const data = await api(`/api/jobs/${state.jobId}`);
    renderStatus(data);
  } catch (error) {
    $("runState").textContent = "error";
    $("logTail").textContent = error.message;
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function loadConfig() {
  const config = await api("/api/config");
  state.config = config;
  if (API_PROFILE_LABELS[config.api?.profile]) $("apiProfile").value = config.api.profile;
  setApiSource(config.api?.key_set ? "env" : "manual");
  syncApiFields();
}

$("analyzeBtn").addEventListener("click", async () => {
  if (!$("url").reportValidity()) return;
  const button = $("analyzeBtn");
  button.dataset.busyLabel = "分析中";
  setBusy(button, true);
  $("analysisBadge").textContent = "分析中";
  $("analysisBadge").classList.remove("is-error");
  try {
    const data = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify(formPayload()),
    });
    renderAnalysis(data);
  } catch (error) {
    $("analysisBadge").textContent = "错误";
    $("analysisBadge").classList.add("is-error");
    $("detectedReason").textContent = error.message;
  } finally {
    setBusy(button, false);
  }
});

$("jobForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("jobForm").reportValidity()) return;
  const button = $("startBtn");
  button.dataset.busyLabel = "启动中";
  setBusy(button, true);
  try {
    const data = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify(formPayload()),
    });
    state.jobId = data.job_id;
    $("runState").textContent = STATUS_LABELS[data.status] || data.status;
    $("jobId").textContent = `任务: ${data.job_id}`;
    $("jobDir").textContent = `目录: ${data.job_dir}`;
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollStatus, 5000);
    await pollStatus();
  } catch (error) {
    $("runState").textContent = "错误";
    $("logTail").textContent = error.message;
    $("logTail").classList.remove("is-hidden");
  } finally {
    setBusy(button, false);
  }
});

loadConfig().catch((error) => {
  $("keyState").textContent = error.message;
  $("keyState").classList.add("is-error");
});

function syncScopeFields() {
  const isFull = selectedScope() === "full";
  for (const panel of document.querySelectorAll("[data-scope-panel='clip']")) {
    setPanelVisible(panel, !isFull);
  }
}

for (const input of document.querySelectorAll("input[name='scope']")) {
  input.addEventListener("change", syncScopeFields);
}
for (const input of document.querySelectorAll("input[name='api_key_source']")) {
  input.addEventListener("change", syncApiFields);
}
$("apiProfile").addEventListener("change", syncApiFields);
$("apiKey").addEventListener("input", syncApiFields);
for (const id of ["contentType", "mode", "voiceStrategy"]) {
  $(id).addEventListener("change", syncVoiceFields);
}
$("dryRun").addEventListener("change", () => {
  syncVoiceFields();
  syncApiFields();
});
$("url").addEventListener("input", () => {
  state.classification = null;
  $("analysisBadge").textContent = "空闲";
  $("detectedType").textContent = "-";
  $("detectedMode").textContent = "-";
  $("detectedVoice").textContent = "-";
  $("detectedConfidence").textContent = "-";
  $("detectedReason").textContent = "";
  syncVoiceFields();
});
syncScopeFields();
syncVoiceFields();
syncApiFields();
