"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const form = byId("email-form");
  const sender = byId("sender");
  const subject = byId("subject");
  const body = byId("body");
  const sampleSelect = byId("sample-select");
  const summarizeButton = byId("summarize-button");
  const promptDetails = byId("prompt-details");
  const promptPreview = byId("prompt-preview");
  const views = ["empty-result", "loading-result", "success-result", "error-result"];
  let config = null;
  let samples = [];
  let busy = false;
  let edited = false;
  let summaryInput = null;
  let promptTimer;
  let promptRequest = 0;
  let promptController = null;
  let summaryController = null;

  const currentEmail = () => ({ sender: sender.value, subject: subject.value, body: body.value });
  const inputSignature = () => JSON.stringify(currentEmail());

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: { Accept: "application/json", ...options.headers },
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("서버 응답을 읽지 못했습니다. 연결 상태를 확인해 주세요.");
    }
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다. 입력 내용과 서버 상태를 확인해 주세요.");
    }
    return data;
  }

  function showError(element, message) {
    element.textContent = message;
    element.hidden = !message;
  }

  function setResult(view, label, state) {
    views.forEach((id) => { byId(id).hidden = id !== view; });
    const status = byId("result-status");
    status.replaceChildren(document.createElement("span"), document.createTextNode(label));
    status.dataset.state = state;
    byId("result-area").setAttribute("aria-busy", String(state === "loading"));
  }

  function updateButton() {
    summarizeButton.disabled = busy || !config?.ready || !body.value.trim();
    summarizeButton.classList.toggle("is-loading", busy);
    byId("summarize-label").textContent = busy ? "요약하는 중" : "이메일 요약하기";
    byId("clear-button").disabled = busy;
    sampleSelect.disabled = busy;
    sender.readOnly = busy;
    subject.readOnly = busy;
    body.readOnly = busy;
  }

  function invalidatePrompt() {
    clearTimeout(promptTimer);
    promptRequest += 1;
    if (promptController) promptController.abort();
    promptPreview.textContent = "현재 입력의 프롬프트를 불러오는 중입니다.";
    if (promptDetails.open) promptTimer = setTimeout(loadPrompt, 300);
  }

  function updateInput({ userEdit = true } = {}) {
    if (userEdit) {
      edited = true;
      sampleSelect.value = "";
    }
    byId("character-count").textContent = `${body.value.length.toLocaleString("ko-KR")} / 20,000자`;
    showError(byId("form-error"), "");
    byId("stale-notice").hidden = summaryInput === null || summaryInput === inputSignature();
    invalidatePrompt();
    updateButton();
  }

  async function loadPrompt() {
    clearTimeout(promptTimer);
    if (!promptDetails.open) return;
    if (promptController) promptController.abort();
    promptController = new AbortController();
    const requestId = ++promptRequest;
    if (!body.value.trim()) {
      promptPreview.textContent = "이메일 본문을 입력하면 프롬프트를 확인할 수 있습니다.";
      return;
    }
    promptPreview.textContent = "프롬프트를 불러오는 중입니다.";
    try {
      const data = await request("/api/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentEmail()),
        signal: promptController.signal,
      });
      if (requestId !== promptRequest) return;
      promptPreview.textContent = data.prompt;
    } catch (error) {
      if (error.name !== "AbortError" && requestId === promptRequest) {
        promptPreview.textContent = `프롬프트를 불러오지 못했습니다. ${error.message}`;
      }
    }
  }

  function applySample(sample) {
    sender.value = sample.sender || "";
    subject.value = sample.subject || "";
    body.value = sample.body || "";
    sampleSelect.value = sample.id;
    updateInput({ userEdit: false });
  }

  function renderConfig(data) {
    config = data;
    byId("model-name").textContent = data.requested_model || "Google Gemini 3.5 Flash Lite";
    byId("model-id").textContent = data.model || "모델 ID 미설정";
    byId("prompt-version").textContent = data.prompt_version || "vulnerable-v1";
    byId("setup-notice").classList.toggle("is-ready", data.ready);
    byId("setup-title").textContent = data.ready ? "요약을 실행할 준비가 되었습니다" : "모델 호출이 대기 상태입니다";
    byId("setup-description").textContent = data.ready
      ? "요약하기를 누르면 입력한 이메일이 실험 모델에 전달됩니다."
      : `${Array.isArray(data.blocked_reasons) && data.blocked_reasons.length ? data.blocked_reasons.join(" ") : "서버의 API 설정을 확인해 주세요."} 이메일 편집과 프롬프트 확인은 가능합니다.`;
    byId("connection-status").textContent = data.ready ? "실행 가능" : "설정 대기";
    updateButton();
  }

  [sender, subject, body].forEach((field) => field.addEventListener("input", () => updateInput()));
  sampleSelect.addEventListener("change", () => {
    edited = true;
    const sample = samples.find((item) => item.id === sampleSelect.value);
    if (sample) applySample(sample);
  });
  byId("clear-button").addEventListener("click", () => {
    sender.value = "";
    subject.value = "";
    body.value = "";
    updateInput();
    body.focus();
  });
  promptDetails.addEventListener("toggle", () => {
    if (promptDetails.open) loadPrompt();
    else {
      clearTimeout(promptTimer);
      promptRequest += 1;
      if (promptController) promptController.abort();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !config?.ready) return;
    if (!body.value.trim()) {
      showError(byId("form-error"), "요약할 이메일 본문을 입력해 주세요.");
      body.focus();
      return;
    }
    busy = true;
    updateButton();
    showError(byId("form-error"), "");
    summaryInput = null;
    byId("stale-notice").hidden = true;
    byId("summary-text").textContent = "";
    byId("result-metrics").textContent = "모델 응답을 기다리는 중";
    setResult("loading-result", "요약 중", "loading");
    const submittedEmail = currentEmail();
    summaryController = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; summaryController.abort(); }, 125000);
    try {
      const result = await request("/api/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(submittedEmail),
        signal: summaryController.signal,
      });
      if (typeof result.summary !== "string" || !result.summary.trim()) throw new Error("모델이 빈 응답을 반환했습니다.");
      byId("summary-text").textContent = result.summary;
      byId("summary-prompt-version").textContent = result.prompt_version || config.prompt_version || "";
      summaryInput = JSON.stringify(submittedEmail);
      const metrics = [];
      if (Number.isFinite(result.latency_ms)) metrics.push(`${(result.latency_ms / 1000).toFixed(2)}초`);
      if (Number.isFinite(result.usage?.total_tokens)) metrics.push(`${result.usage.total_tokens.toLocaleString("ko-KR")} tokens`);
      byId("result-metrics").textContent = metrics.length ? metrics.join(" · ") : "요약이 완료되었습니다";
      setResult("success-result", "요약 완료", "success");
    } catch (error) {
      byId("result-error-message").textContent = timedOut
        ? "응답 대기 시간이 초과되었습니다. 서버에서 요청이 계속 처리 중일 수 있습니다."
        : error.message;
      byId("result-metrics").textContent = "완료된 응답이 없습니다";
      setResult("error-result", "요청 실패", "error");
    } finally {
      clearTimeout(timeout);
      summaryController = null;
      busy = false;
      updateButton();
    }
  });

  async function initialize() {
    const results = await Promise.allSettled([request("/api/config"), request("/api/samples")]);
    const [configuration, sampleData] = results;
    if (configuration.status === "fulfilled") renderConfig(configuration.value);
    else {
      byId("setup-title").textContent = "연결 설정을 확인하지 못했습니다";
      byId("setup-description").textContent = "서버 상태를 확인한 뒤 페이지를 새로고침해 주세요. 이메일 편집은 가능합니다.";
      byId("connection-status").textContent = "연결 오류";
      byId("model-id").textContent = "설정 확인 실패";
      showError(byId("page-error"), configuration.reason.message);
    }
    if (sampleData.status === "fulfilled" && Array.isArray(sampleData.value)) {
      samples = sampleData.value;
      for (const sample of samples) {
        const option = document.createElement("option");
        option.value = sample.id;
        option.textContent = sample.title;
        sampleSelect.append(option);
      }
      if (samples.length && !edited) applySample(samples[0]);
    } else {
      const sampleError = "샘플 이메일을 불러오지 못했습니다. 이메일을 직접 입력해 주세요.";
      const existing = byId("page-error").textContent;
      showError(byId("page-error"), existing ? `${existing} ${sampleError}` : sampleError);
    }
    updateButton();
  }

  initialize();
})();
