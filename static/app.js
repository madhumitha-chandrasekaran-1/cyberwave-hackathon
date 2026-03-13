/**
 * PhysioBot frontend — session management, voice commands, and status polling.
 * Vanilla JS, no framework required.
 */

"use strict";

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
const state = {
  sessionId: null,
  phase: "idle",
  pollingTimer: null,
  mediaRecorder: null,
  audioChunks: [],
  isRecordingMic: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// DOM references
// ─────────────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const els = {
  phaseBadge:         $("phaseBadge"),
  phaseText:          $("phaseText"),
  sessionIdDisplay:   $("sessionIdDisplay"),
  setupPanel:         $("setupPanel"),
  sessionPanel:       $("sessionPanel"),
  exerciseSelect:     $("exerciseSelect"),
  btnStart:           $("btnStart"),
  btnRecord:          $("btnRecord"),
  btnEvaluate:        $("btnEvaluate"),
  btnSpeak:           $("btnSpeak"),
  btnNewSession:      $("btnNewSession"),
  btnMic:             $("btnMic"),
  micHint:            $("micHint"),
  transcriptDisplay:  $("transcriptDisplay"),
  evaluationCard:     $("evaluationCard"),
  scoreRing:          $("scoreRing"),
  scoreNum:           $("scoreNum"),
  feedbackText:       $("feedbackText"),
  correctionsWrap:    $("correctionsWrap"),
  correctionsList:    $("correctionsList"),
  audioWrap:          $("audioWrap"),
  feedbackAudio:      $("feedbackAudio"),
  historyCard:        $("historyCard"),
  historyBody:        $("historyBody"),
  toastContainer:     $("toastContainer"),
};

// ─────────────────────────────────────────────────────────────────────────────
// Toast notifications
// ─────────────────────────────────────────────────────────────────────────────
/**
 * Show a temporary toast notification.
 * @param {string} message
 * @param {"info"|"success"|"error"|"warning"} type
 * @param {number} duration  milliseconds before auto-dismiss
 */
function toast(message, type = "info", duration = 4000) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  el.addEventListener("click", () => el.remove());
  els.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase badge helpers
// ─────────────────────────────────────────────────────────────────────────────
const PHASE_CONFIG = {
  idle:          { label: "Idle",          cls: "" },
  demonstrating: { label: "Arm Demo",      cls: "busy" },
  recording:     { label: "Recording…",   cls: "warn" },
  evaluating:    { label: "Evaluating…",  cls: "busy" },
  feedback:      { label: "Feedback Ready", cls: "done" },
  complete:      { label: "Complete",      cls: "active" },
};

function updatePhaseBadge(phase) {
  const cfg = PHASE_CONFIG[phase] || { label: phase, cls: "" };
  els.phaseText.textContent = cfg.label;
  els.phaseBadge.className = "phase-badge " + cfg.cls;
}

// ─────────────────────────────────────────────────────────────────────────────
// Button state management
// ─────────────────────────────────────────────────────────────────────────────
function setButtonLoading(btn, loading, originalText = null) {
  if (loading) {
    btn.dataset.originalText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> Loading…`;
    btn.disabled = true;
  } else {
    btn.innerHTML = originalText || btn.dataset.originalText || btn.innerHTML;
    btn.disabled = false;
  }
}

function refreshActionButtons(phase) {
  const { btnRecord, btnEvaluate, btnSpeak } = els;

  btnRecord.disabled   = phase !== "demonstrating" && phase !== "feedback";
  btnEvaluate.disabled = phase !== "evaluating" && phase !== "recording";
  btnSpeak.disabled    = phase !== "feedback";

  // Make Record available right after start too
  if (phase === "demonstrating") {
    btnRecord.disabled = false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// API calls
// ─────────────────────────────────────────────────────────────────────────────
/**
 * Generic JSON fetch wrapper with error handling.
 */
async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) { /* ignore parse errors */ }
    throw new Error(detail);
  }
  return response;
}

async function apiJSON(path, options = {}) {
  const resp = await apiFetch(path, options);
  return resp.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Session flow
// ─────────────────────────────────────────────────────────────────────────────

/** Start a new rehab session. */
async function startSession() {
  const exerciseName = els.exerciseSelect.value;
  setButtonLoading(els.btnStart, true);

  try {
    const data = await apiJSON("/api/session/start", {
      method: "POST",
      body: JSON.stringify({ exercise_name: exerciseName }),
    });

    state.sessionId = data.session_id;
    state.phase = data.phase;

    // Show session panel
    els.setupPanel.classList.add("hidden");
    els.sessionPanel.classList.remove("hidden");
    els.sessionIdDisplay.textContent = `Session: ${data.session_id.slice(0, 8)}…`;
    els.sessionIdDisplay.classList.remove("hidden");

    updatePhaseBadge(data.phase);
    refreshActionButtons(data.phase);
    startPolling();

    toast(
      `Session started! ${data.cyberwave_run_id ? "Robot arm is demonstrating the exercise." : data.message}`,
      "success",
    );
  } catch (err) {
    toast(`Failed to start session: ${err.message}`, "error");
  } finally {
    setButtonLoading(els.btnStart, false, "▶ Start Session");
  }
}

/** Trigger camera recording. */
async function recordAttempt() {
  if (!state.sessionId) return;
  setButtonLoading(els.btnRecord, true);

  try {
    const data = await apiJSON(`/api/session/${state.sessionId}/record`, {
      method: "POST",
    });
    state.phase = data.phase;
    updatePhaseBadge("recording");
    toast("Recording started — perform your exercise now!", "info", 6000);

    // After 11s (recording + buffer) enable evaluate button
    setTimeout(() => {
      els.btnEvaluate.disabled = false;
      toast("Recording complete. Click Evaluate to analyse your form.", "success");
    }, 11000);
  } catch (err) {
    toast(`Record failed: ${err.message}`, "error");
  } finally {
    setButtonLoading(els.btnRecord, false, "⏺ Record My Attempt");
  }
}

/** Send frames to VLM and display result. */
async function evaluateSession() {
  if (!state.sessionId) return;
  setButtonLoading(els.btnEvaluate, true);
  toast("Sending frames to AI evaluator…", "info");

  try {
    const data = await apiJSON(`/api/session/${state.sessionId}/evaluate`, {
      method: "POST",
    });

    state.phase = data.phase;
    updatePhaseBadge("feedback");
    refreshActionButtons("feedback");

    renderEvaluation(data);
    updateHistory();
    toast(`Evaluation complete! Score: ${data.score}/10`, data.is_correct ? "success" : "warning");
  } catch (err) {
    toast(`Evaluation failed: ${err.message}`, "error");
  } finally {
    setButtonLoading(els.btnEvaluate, false, "🔍 Evaluate");
  }
}

/** Fetch TTS audio and play it. */
async function speakFeedback() {
  if (!state.sessionId) return;
  setButtonLoading(els.btnSpeak, true);
  toast("Generating speech…", "info");

  try {
    const resp = await apiFetch(`/api/session/${state.sessionId}/speak`, {
      method: "POST",
    });

    const audioBlob = await resp.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    els.feedbackAudio.src = audioUrl;
    els.audioWrap.classList.remove("hidden");
    els.feedbackAudio.play().catch(() => {
      // Auto-play may be blocked — user sees the audio player
      toast("Audio ready — press play on the player below.", "info");
    });

    toast("Speaking feedback!", "success");
  } catch (err) {
    toast(`TTS failed: ${err.message}`, "error");
  } finally {
    setButtonLoading(els.btnSpeak, false, "🔊 Speak Feedback");
  }
}

/** Reset UI to start a new session. */
function resetToNewSession() {
  stopPolling();
  state.sessionId = null;
  state.phase = "idle";

  els.setupPanel.classList.remove("hidden");
  els.sessionPanel.classList.add("hidden");
  els.sessionIdDisplay.classList.add("hidden");
  els.evaluationCard.classList.add("hidden");
  els.historyCard.classList.add("hidden");
  els.audioWrap.classList.add("hidden");
  els.correctionsWrap.classList.add("hidden");
  els.historyBody.innerHTML = "";

  updatePhaseBadge("idle");
  toast("Ready for a new session.", "info");
}

// ─────────────────────────────────────────────────────────────────────────────
// Evaluation rendering
// ─────────────────────────────────────────────────────────────────────────────

function renderEvaluation(data) {
  const score = data.score ?? 0;
  const pct = Math.round(score * 10);

  els.scoreRing.style.setProperty("--pct", pct);
  els.scoreNum.textContent = score;
  els.feedbackText.textContent = data.feedback || "No feedback provided.";

  // Corrections
  const corrections = data.corrections || [];
  if (corrections.length > 0) {
    els.correctionsList.innerHTML = corrections
      .map(
        (c) =>
          `<div class="correction-item"><span class="icon">⚠️</span><span>${escapeHtml(c)}</span></div>`,
      )
      .join("");
    els.correctionsWrap.classList.remove("hidden");
  } else {
    els.correctionsWrap.classList.add("hidden");
  }

  els.evaluationCard.classList.remove("hidden");
}

function updateHistory() {
  if (!state.sessionId) return;

  apiJSON(`/api/session/${state.sessionId}/status`)
    .then((data) => {
      const history = data.history || [];
      if (history.length === 0) return;

      els.historyBody.innerHTML = history
        .map((a) => {
          const score = a.evaluation?.score ?? "—";
          const isCorrect = a.evaluation?.is_correct;
          const feedback = a.evaluation?.feedback || "";
          const scoreClass =
            score >= 8 ? "badge-good" : score >= 6 ? "badge-warn" : "badge-bad";
          const tick = isCorrect ? "✅" : "❌";
          const time = new Date(a.timestamp).toLocaleTimeString();
          return `<tr>
            <td>${a.attempt_number}</td>
            <td>${time}</td>
            <td class="${scoreClass}">${score}/10</td>
            <td>${tick}</td>
            <td>${escapeHtml(feedback.slice(0, 60))}${feedback.length > 60 ? "…" : ""}</td>
          </tr>`;
        })
        .join("");

      els.historyCard.classList.remove("hidden");
    })
    .catch(() => {/* ignore polling errors */});
}

// ─────────────────────────────────────────────────────────────────────────────
// Status polling
// ─────────────────────────────────────────────────────────────────────────────

function startPolling() {
  stopPolling();
  state.pollingTimer = setInterval(pollStatus, 2000);
}

function stopPolling() {
  if (state.pollingTimer) {
    clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

async function pollStatus() {
  if (!state.sessionId) return;

  try {
    const data = await apiJSON(`/api/session/${state.sessionId}/status`);
    const newPhase = data.phase;

    if (newPhase !== state.phase) {
      state.phase = newPhase;
      updatePhaseBadge(newPhase);
      refreshActionButtons(newPhase);

      // Auto-enable evaluate when recording finishes
      if (newPhase === "evaluating") {
        els.btnEvaluate.disabled = false;
        toast("Recording complete! Click Evaluate.", "success");
      }
    }
  } catch (_) {
    // Session may not exist yet; ignore silently
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Voice command (microphone)
// ─────────────────────────────────────────────────────────────────────────────

async function startMicRecording() {
  if (state.isRecordingMic) return;

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    toast("Microphone access denied. Please allow mic access.", "error");
    return;
  }

  state.audioChunks = [];
  state.isRecordingMic = true;
  els.btnMic.classList.add("recording");
  els.micHint.textContent = "Recording… tap again to stop.";

  const options = { mimeType: "audio/webm" };
  state.mediaRecorder = new MediaRecorder(stream, options);

  state.mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) state.audioChunks.push(e.data);
  };

  state.mediaRecorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    els.btnMic.classList.remove("recording");
    state.isRecordingMic = false;
    els.micHint.textContent = "Processing voice command…";

    const audioBlob = new Blob(state.audioChunks, { type: "audio/webm" });
    await sendVoiceCommand(audioBlob);
  };

  state.mediaRecorder.start();
}

function stopMicRecording() {
  if (!state.isRecordingMic || !state.mediaRecorder) return;
  state.mediaRecorder.stop();
}

async function sendVoiceCommand(audioBlob) {
  const formData = new FormData();
  formData.append("audio", audioBlob, "command.webm");

  try {
    const resp = await fetch("/api/voice/command", {
      method: "POST",
      body: formData,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    const transcript = data.transcript || "(empty)";
    els.transcriptDisplay.textContent = `"${transcript}" → action: ${data.action}${data.exercise ? ` (${data.exercise})` : ""}`;
    els.transcriptDisplay.classList.remove("hidden");
    els.micHint.textContent = "Tap mic to record another command.";

    // Act on the parsed command
    await executeVoiceAction(data);
  } catch (err) {
    els.micHint.textContent = "Command failed. Try again.";
    toast(`Voice command error: ${err.message}`, "error");
  }
}

async function executeVoiceAction(command) {
  const { action, exercise } = command;

  if (action === "start") {
    if (exercise) els.exerciseSelect.value = exercise;
    toast(`Voice command: starting ${exercise || "exercise"}`, "info");
    await startSession();
  } else if (action === "stop") {
    toast("Voice command: stopping session.", "info");
    resetToNewSession();
  } else if (action === "repeat") {
    toast("Voice command: re-recording attempt.", "info");
    await recordAttempt();
  } else if (action === "status") {
    await pollStatus();
    toast(`Current phase: ${state.phase}`, "info");
  } else {
    toast(`Unrecognised command: "${command.transcript}"`, "warning");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─────────────────────────────────────────────────────────────────────────────
// Event listeners
// ─────────────────────────────────────────────────────────────────────────────

els.btnStart.addEventListener("click", startSession);
els.btnRecord.addEventListener("click", recordAttempt);
els.btnEvaluate.addEventListener("click", evaluateSession);
els.btnSpeak.addEventListener("click", speakFeedback);
els.btnNewSession.addEventListener("click", resetToNewSession);

// Mic: tap to start, tap again to stop
els.btnMic.addEventListener("click", () => {
  if (state.isRecordingMic) {
    stopMicRecording();
  } else {
    startMicRecording();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
updatePhaseBadge("idle");
refreshActionButtons("idle");

// Verify service health on load
fetch("/health")
  .then((r) => r.json())
  .then((d) => {
    if (d.status === "ok") {
      console.info("PhysioBot service healthy:", d);
    }
  })
  .catch(() => toast("Could not reach PhysioBot API.", "error"));
