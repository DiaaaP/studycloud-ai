const state = {
  user: null,
  lectures: [],
  radar: [],
  activeLecture: null,
  questionIndex: 0,
  answers: [],
  confidences: [],
  quizSubmitted: false,
  quizResult: null,
  flashcardIndex: 0,
  flashcardRevealed: false,
  activeRecognition: null,
  voiceTarget: null,
};

const TOKEN_KEY = "studycloud-token";

const routes = {
  dashboard: ["your_study_workspace", "Dashboard"],
  upload: ["add_course_material", "Upload lecture"],
  summary: ["review_essentials", "AI summary"],
  quiz: ["test_recall", "Practice quiz"],
  proofloop: ["repair_knowledge", "ProofLoop radar"],
  roadmap: ["plan_session", "Exam roadmap"],
};

const supportedExtensions = ["pdf", "pptx", "docx", "txt", "md", "html", "htm", "epub", "csv", "srt", "vtt"];
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const i18n = window.StudyCloudI18n;
const t = (key, variables) => i18n.t(key, variables);
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[character]));

function apiErrorMessage(body = {}) {
  const detail = body.detail;
  if (Array.isArray(detail)) {
    return detail.map(error => {
      const field = error?.loc?.at(-1);
      if (field === "username") return t("username_rules");
      if (field === "email") return t("email_rules");
      if (field === "password") return t("password_rules");
      if (field === "full_name") return t("full_name_rules");
      return error?.msg || t("invalid_data");
    }).join(" ");
  }
  if (typeof detail === "string") return t(detail);
  if (detail && typeof detail === "object") return detail.message || t("invalid_data");
  return t("Something went wrong");
}

async function api(path, options = {}) {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`/api${path}`, { cache: "no-store", ...options, headers });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) showAuth(t("session_expired"));
    throw new Error(apiErrorMessage(body));
  }
  return body;
}

function showAuth(message = "") {
  state.user = null;
  localStorage.removeItem(TOKEN_KEY);
  $("#app-shell").hidden = true;
  $("#bottom-nav").hidden = true;
  $("#auth-shell").hidden = false;
  $("#profile-menu").hidden = true;
  const error = $("#auth-error");
  error.textContent = message;
  error.hidden = !message;
}

function showWorkspace(user) {
  state.user = user;
  $("#auth-shell").hidden = true;
  $("#app-shell").hidden = false;
  $("#bottom-nav").hidden = false;
  $("#profile-name").textContent = user.full_name;
  $("#profile-email").textContent = `${user.username} · ${user.email}`;
  $("#profile-toggle").textContent = user.full_name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase() || "SC";
  window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
}

async function establishSession(payload) {
  localStorage.setItem(TOKEN_KEY, payload.access_token);
  showWorkspace(payload.user);
  await refreshDashboard();
  route();
}

function selectAuthMode(mode) {
  const register = mode === "register";
  $("#login-form").hidden = register;
  $("#register-form").hidden = !register;
  $("#show-login").classList.toggle("active", !register);
  $("#show-register").classList.toggle("active", register);
  $("#auth-title").textContent = t(register ? "create_account" : "sign_in");
  $("#auth-subtitle").textContent = t(register ? "register_subtitle" : "login_subtitle");
  $("#auth-error").hidden = true;
}

async function submitAuth(form, path, payload) {
  const button = form.querySelector('button[type="submit"]');
  const original = button.textContent;
  button.disabled = true;
  button.textContent = t("please_wait");
  $("#auth-error").hidden = true;
  try {
    await establishSession(await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }));
    form.reset();
  } catch (error) {
    $("#auth-error").textContent = error.message;
    $("#auth-error").hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function authorizedFile(url, openInNewTab = false) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) || ""}` },
  });
  if (response.status === 401) {
    showAuth(t("session_expired"));
    throw new Error(t("session_expired"));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(apiErrorMessage(body));
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  if (openInNewTab) {
    window.open(blobUrl, "_blank", "noopener");
  } else {
    const link = document.createElement("a");
    link.href = blobUrl;
    const disposition = response.headers.get("content-disposition") || "";
    link.download = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "studycloud-export.md";
    link.click();
  }
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 3600);
}

function route() {
  const name = location.hash.slice(1).split("/")[0] || "dashboard";
  const current = routes[name] ? name : "dashboard";
  $$(".view").forEach(view => { view.hidden = view.dataset.view !== current; });
  $$('[data-route]').forEach(link => link.classList.toggle("active", link.dataset.route === current));
  $("#page-eyebrow").textContent = t(routes[current][0]);
  $("#page-title").textContent = t(routes[current][1]);
  document.title = `${t(routes[current][1])} · StudyCloud AI`;
  if (current === "summary") renderSummary();
  if (current === "quiz") renderQuiz();
  if (current === "proofloop") renderProofLoop();
  if (current === "roadmap") renderSavedRoadmap();
  window.scrollTo({ top: 0, behavior: "auto" });
}

function formatNumber(value) {
  return new Intl.NumberFormat(i18n.language).format(value || 0);
}

function unitLabel(lecture) {
  if (lecture.file_type === "PPTX") return t(lecture.pages === 1 ? "slide" : "slides");
  if (lecture.file_type === "PDF") return t(lecture.pages === 1 ? "page" : "pages");
  if (lecture.file_type === "EPUB") return t(lecture.pages === 1 ? "chapter" : "chapters");
  return t(lecture.pages === 1 ? "section" : "sections");
}

async function refreshDashboard() {
  const [stats, lectures, radar] = await Promise.all([api("/stats"), api("/lectures"), api("/radar")]);
  state.lectures = lectures;
  state.radar = radar;
  $("#metrics").innerHTML = [
    [t("materials"), stats.lectures, "▤"],
    [t("words_analyzed"), formatNumber(stats.words), "Aa"],
    [t("quizzes"), stats.quizzes, "?"],
    [t("accuracy"), `${stats.accuracy}%`, "◎"],
    [t("knowledge_debts"), stats.blind_spots ? `${stats.open_gaps} · ${stats.blind_spots} ${t("blind")}` : stats.open_gaps, "◉"],
  ].map(([label, value, icon]) => `<article class="metric"><i>${icon}</i><span>${label}</span><strong>${value}</strong></article>`).join("");

  renderLectureList(lectures);
}

function renderLectureList(lectures) {
  $("#lecture-list").innerHTML = lectures.length ? lectures.map(lecture => `
    <article class="lecture-row">
      <div class="lecture-icon">${escapeHtml(lecture.file_type || "FILE")}</div>
      <div class="lecture-info"><h3>${escapeHtml(lecture.title)}</h3><p>${lecture.pages} ${unitLabel(lecture)} · ${formatNumber(lecture.word_count)} ${t("words")} · ${escapeHtml(lecture.engine)}</p></div>
      <div class="lecture-actions">
        <button class="mini-button primary" data-summary="${lecture.id}">${t("study_pack")}</button>
        <button class="mini-button" data-quiz="${lecture.id}">${t("practice_quiz")}</button>
        ${lecture.id === "demo-raft" ? "" : `<button class="mini-button danger" data-delete="${lecture.id}" aria-label="${t("delete")}" title="${t("delete")}">×</button>`}
      </div>
    </article>`).join("") : `<div class="empty-state"><span>⇧</span><h2>${t("library_empty")}</h2><p>${t("upload_first")}</p></div>`;

  $$('[data-summary]').forEach(button => button.addEventListener("click", () => openLecture(button.dataset.summary, "summary")));
  $$('[data-quiz]').forEach(button => button.addEventListener("click", () => openLecture(button.dataset.quiz, "quiz")));
  $$('[data-delete]').forEach(button => button.addEventListener("click", async () => {
    if (!window.confirm(t("delete_confirm"))) return;
    try {
      await api(`/lectures/${button.dataset.delete}`, { method: "DELETE" });
      if (state.activeLecture?.id === button.dataset.delete) state.activeLecture = null;
      localStorage.removeItem(`studycloud-quiz-${button.dataset.delete}`);
      await refreshDashboard();
      toast(t("lecture_deleted"));
    } catch (error) {
      toast(error.message);
    }
  }));
}

$("#library-search").addEventListener("input", event => {
  const query = event.target.value.trim().toLowerCase();
  const filtered = state.lectures.filter(lecture =>
    [lecture.title, lecture.filename, lecture.file_type, lecture.engine]
      .some(value => String(value || "").toLowerCase().includes(query))
  );
  renderLectureList(filtered);
});

async function openLecture(id, destination) {
  try {
    state.activeLecture = await api(`/lectures/${id}`);
    state.questionIndex = 0;
    state.answers = Array(state.activeLecture.quiz.length).fill(null);
    state.confidences = Array(state.activeLecture.quiz.length).fill(null);
    state.quizSubmitted = false;
    state.quizResult = null;
    state.flashcardIndex = 0;
    state.flashcardRevealed = false;
    $("#edit-pack-form").hidden = true;
    $("#defense-input").value = "";
    $("#defense-result").hidden = true;
    location.hash = destination;
    route();
  } catch (error) {
    toast(error.message);
  }
}

function renderSummary() {
  const lecture = state.activeLecture;
  $("#summary-empty").hidden = Boolean(lecture);
  $("#summary-content").hidden = !lecture;
  if (!lecture) return;
  $("#summary-title").textContent = lecture.title;
  $("#summary-meta").innerHTML = `<span>${escapeHtml(lecture.file_type)} · ${lecture.pages} ${unitLabel(lecture)}</span><span>${formatNumber(lecture.word_count)} ${t("words")}</span><span>${escapeHtml(lecture.engine)}</span>`;
  $("#summary-text").textContent = lecture.summary;
  $("#engine-note").textContent = t("generated_with", { engine: lecture.engine });
  $("#key-ideas").innerHTML = lecture.key_ideas.map(idea => `<li>${escapeHtml(idea)}</li>`).join("");
  $("#export-link").href = `/api/lectures/${lecture.id}/export`;
  $("#source-link").href = `/api/lectures/${lecture.id}/source`;
  $("#edit-pack").hidden = lecture.id === "demo-raft";
  $("#source-link").hidden = lecture.id === "demo-raft";
  $("#edit-title").value = lecture.title;
  $("#edit-summary").value = lecture.summary;
  $("#edit-ideas").value = lecture.key_ideas.join("\n");
  renderFlashcard();
}

$("#export-link").addEventListener("click", event => {
  event.preventDefault();
  if (!state.activeLecture) return;
  authorizedFile(`/api/lectures/${state.activeLecture.id}/export`).catch(error => toast(error.message));
});

$("#source-link").addEventListener("click", event => {
  event.preventDefault();
  if (!state.activeLecture) return;
  authorizedFile(`/api/lectures/${state.activeLecture.id}/source`, true).catch(error => toast(error.message));
});

$("#edit-pack").addEventListener("click", () => {
  if (!state.activeLecture) return;
  $("#edit-pack-form").hidden = false;
  $("#edit-title").focus();
});

$("#cancel-edit-pack").addEventListener("click", () => {
  $("#edit-pack-form").hidden = true;
  renderSummary();
});

$("#edit-pack-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.activeLecture) return;
  const keyIdeas = $("#edit-ideas").value.split("\n").map(value => value.trim()).filter(Boolean);
  try {
    state.activeLecture = await api(`/lectures/${state.activeLecture.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: $("#edit-title").value.trim(),
        summary: $("#edit-summary").value.trim(),
        key_ideas: keyIdeas,
      }),
    });
    $("#edit-pack-form").hidden = true;
    await refreshDashboard();
    renderSummary();
    toast(t("pack_updated"));
  } catch (error) {
    toast(error.message);
  }
});

function renderFlashcard() {
  const cards = state.activeLecture?.flashcards || [];
  const stage = $("#flashcard-stage");
  $("#flashcard-count").textContent = cards.length ? `${state.flashcardIndex + 1} / ${cards.length}` : t("no_cards");
  if (!cards.length) {
    stage.innerHTML = `<strong>${t("no_cards")}</strong><p>${t("not_enough_concepts")}</p>`;
    return;
  }
  const card = cards[state.flashcardIndex];
  stage.innerHTML = state.flashcardRevealed
    ? `<span>${t("answer")} · ${escapeHtml(card.source_ref || t("source"))}</span><p>${escapeHtml(card.back)}</p>`
    : `<span>${t("recall_before")}</span><strong>${escapeHtml(card.front)}</strong>`;
  $("#flip-card").textContent = state.flashcardRevealed ? t("show_prompt") : t("reveal_answer");
}

$("#flip-card").addEventListener("click", () => { state.flashcardRevealed = !state.flashcardRevealed; renderFlashcard(); });
$("#flashcard-stage").addEventListener("click", () => { state.flashcardRevealed = !state.flashcardRevealed; renderFlashcard(); });
$("#previous-card").addEventListener("click", () => {
  const count = state.activeLecture?.flashcards?.length || 0;
  if (!count) return;
  state.flashcardIndex = (state.flashcardIndex - 1 + count) % count;
  state.flashcardRevealed = false;
  renderFlashcard();
});
$("#next-card").addEventListener("click", () => {
  const count = state.activeLecture?.flashcards?.length || 0;
  if (!count) return;
  state.flashcardIndex = (state.flashcardIndex + 1) % count;
  state.flashcardRevealed = false;
  renderFlashcard();
});

$("#ask-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.activeLecture) return;
  const question = $("#ask-input").value.trim();
  const result = $("#ask-result");
  result.hidden = false;
  result.innerHTML = t("searching");
  try {
    const response = await api(`/lectures/${state.activeLecture.id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const evidence = response.sources.map(source => `<div class="source-evidence"><strong>${escapeHtml(source.ref)}</strong>${escapeHtml(source.text)}</div>`).join("");
    result.innerHTML = `<strong>${t("answer_material")}</strong>${escapeHtml(response.answer)}${evidence}`;
  } catch (error) {
    result.textContent = error.message;
  }
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const voiceButtons = [$("#voice-ask"), $("#voice-defense")];

function syncVoiceButtons() {
  voiceButtons.forEach(button => {
    if (!button) return;
    const listening = state.voiceTarget === button.id;
    button.disabled = !SpeechRecognition;
    button.classList.toggle("listening", listening);
    const label = !SpeechRecognition ? t("voice_unavailable") : listening ? t("listening") : t("start_voice");
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    button.textContent = button.id === "voice-ask" ? (listening ? "■" : "●") : label;
  });
}

function setupVoiceInput(buttonId, inputId) {
  const button = $(`#${buttonId}`);
  const input = $(`#${inputId}`);
  button.addEventListener("click", () => {
    if (!SpeechRecognition) return;
    if (state.activeRecognition) {
      state.activeRecognition.stop();
      return;
    }
    const recognition = new SpeechRecognition();
    const existing = input.value.trim();
    recognition.lang = i18n.speechLocale();
    recognition.interimResults = true;
    recognition.continuous = true;
    state.activeRecognition = recognition;
    state.voiceTarget = buttonId;
    syncVoiceButtons();
    recognition.onresult = event => {
      const transcript = [...event.results].map(result => result[0].transcript).join(" ").trim();
      input.value = `${existing}${existing && transcript ? " " : ""}${transcript}`;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    recognition.onerror = event => {
      if (event.error !== "aborted") toast(t("voice_stopped", { error: event.error }));
    };
    recognition.onend = () => {
      if (state.activeRecognition === recognition) {
        state.activeRecognition = null;
        state.voiceTarget = null;
        syncVoiceButtons();
      }
    };
    recognition.start();
  });
}

setupVoiceInput("voice-ask", "ask-input");
setupVoiceInput("voice-defense", "defense-input");
syncVoiceButtons();

$("#defense-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.activeLecture) return;
  const result = $("#defense-result");
  result.hidden = false;
  result.innerHTML = t("evaluating");
  try {
    const response = await api(`/lectures/${state.activeLecture.id}/defend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        explanation: $("#defense-input").value.trim(),
        confidence: Number($("#defense-confidence").value),
      }),
    });
    const covered = response.covered.map(item => `<span class="concept-chip">${escapeHtml(item)}</span>`).join("");
    const missing = response.missing.map(item => `<span class="concept-chip missing">${escapeHtml(item)}</span>`).join("");
    const blindSpotText = response.blind_spots.length
      ? `<p><strong>${t(response.blind_spots.length === 1 ? "confidence_trap_one" : "confidence_trap_many", { count: response.blind_spots.length })}</strong>${t("omissions_added")}</p>`
      : "";
    const evidence = response.sources.map(source => `<div class="source-evidence"><strong>${escapeHtml(source.ref)}</strong>${escapeHtml(source.text)}</div>`).join("");
    result.innerHTML = `<div class="defense-score"><strong>${response.coverage}%</strong><span>${t("coverage", { confidence: response.confidence })}</span></div><p>${escapeHtml(response.feedback)}</p>${blindSpotText}<div class="concept-chips">${covered}${missing}</div><p><strong>${t("next_prompt")}:</strong> ${escapeHtml(response.next_prompt)}</p>${evidence}`;
  } catch (error) {
    result.textContent = error.message;
  }
});

function renderQuiz() {
  const lecture = state.activeLecture;
  $("#quiz-empty").hidden = Boolean(lecture);
  $("#quiz-content").hidden = !lecture;
  if (!lecture) return;
  const quiz = lecture.quiz;
  const index = state.questionIndex;
  const question = quiz[index];
  $("#quiz-context").textContent = lecture.title;
  $("#quiz-count").textContent = `${index + 1} / ${quiz.length}`;
  $("#quiz-progress").style.width = `${((index + 1) / quiz.length) * 100}%`;
  $("#question-label").textContent = `${t("question_of", { current: index + 1, total: quiz.length })} · ${question.concept || t("key_concept")}`;
  $("#question-text").textContent = question.question;
  $$('[data-confidence]').forEach(button => {
    button.classList.toggle("selected", state.confidences[index] === Number(button.dataset.confidence));
    button.disabled = state.quizSubmitted;
    button.onclick = () => {
      state.confidences[index] = Number(button.dataset.confidence);
      renderQuiz();
    };
  });
  const letters = ["A", "B", "C", "D"];
  $("#quiz-options").innerHTML = question.options.map((option, optionIndex) => {
    const selected = state.answers[index] === optionIndex;
    let classes = selected ? " selected" : "";
    if (state.quizSubmitted && optionIndex === question.correct_index) classes += " correct";
    if (state.quizSubmitted && selected && optionIndex !== question.correct_index) classes += " incorrect";
    return `<button class="option${classes}" type="button" data-option="${optionIndex}" ${state.quizSubmitted ? "disabled" : ""}><b>${letters[optionIndex]}</b><span>${escapeHtml(option)}</span><i></i></button>`;
  }).join("");
  $$('[data-option]').forEach(button => button.addEventListener("click", () => {
    state.answers[index] = Number(button.dataset.option);
    renderQuiz();
  }));

  const explanation = $("#explanation");
  explanation.hidden = !state.quizSubmitted;
  explanation.innerHTML = state.quizSubmitted ? `<strong>${t("evidence")} · ${escapeHtml(question.source_ref || t("source"))}</strong><br>${escapeHtml(question.explanation)}` : "";
  const result = $("#quiz-result");
  result.hidden = !state.quizSubmitted;
  if (state.quizSubmitted && state.quizResult) {
    const gaps = state.quizResult.knowledge_gaps.length;
    const blind = state.quizResult.blind_spots.length;
    result.innerHTML = `<strong>${state.quizResult.score} / ${state.quizResult.total}</strong>${gaps ? t("debts_added", { count: gaps }) : t("no_new_debts")}${blind ? t("blind_found", { count: blind }) : ""}`;
  }
  $("#previous-question").disabled = index === 0;
  const next = $("#next-question");
  next.textContent = index === quiz.length - 1 ? (state.quizSubmitted ? t("open_proofloop") : t("finish_quiz")) : t("next_question");
}

$("#previous-question").addEventListener("click", () => {
  state.questionIndex = Math.max(0, state.questionIndex - 1);
  renderQuiz();
});

$("#next-question").addEventListener("click", async () => {
  if (!state.activeLecture) return;
  const last = state.questionIndex === state.activeLecture.quiz.length - 1;
  if (last && state.quizSubmitted) {
    location.hash = "proofloop";
    return;
  }
  if (state.answers[state.questionIndex] === null) {
    toast(t("choose_answer"));
    return;
  }
  if (state.confidences[state.questionIndex] === null) {
    toast(t("rate_confidence"));
    return;
  }
  if (!last) {
    state.questionIndex += 1;
    renderQuiz();
    return;
  }
  try {
    state.quizResult = await api(`/lectures/${state.activeLecture.id}/quiz`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: state.answers, confidences: state.confidences }),
    });
    state.quizSubmitted = true;
    toast(t("quiz_complete", { score: state.quizResult.score, total: state.quizResult.total }));
    renderQuiz();
  } catch (error) {
    toast(error.message);
  }
});

async function renderProofLoop() {
  try {
    state.radar = await api("/radar");
  } catch (error) {
    toast(error.message);
    return;
  }
  const gaps = state.radar;
  const health = gaps.length ? Math.round(gaps.reduce((total, gap) => total + gap.mastery, 0) / gaps.length) : 100;
  const active = gaps.filter(gap => gap.priority > 0);
  const due = gaps.filter(gap => new Date(gap.next_review) <= new Date()).length;
  const blindSpots = gaps.filter(gap => gap.is_blind_spot).length;
  $("#radar-score").textContent = health;
  $("#radar-summary").innerHTML = [
    [t("active_debts"), active.length],
    [t("confidence_traps"), blindSpots],
    [t("due_review"), due],
    [t("concepts_tracked"), gaps.length],
  ].map(([label, value]) => `<article class="radar-stat"><span>${label}</span><strong>${value}</strong></article>`).join("");
  $("#gap-list").innerHTML = gaps.length ? gaps.map(gap => `
    <article class="gap-card">
      <div>${gap.is_blind_spot ? `<span class="blindspot-badge">${t("confidence_trap", { confidence: gap.last_confidence })}</span>` : ""}<p class="eyebrow">${escapeHtml(gap.lecture_title)} · ${escapeHtml(gap.source_ref)}</p><h3>${escapeHtml(gap.concept)}</h3><p>${t("mistakes_recalls", { mistakes: gap.mistakes, successes: gap.successes })}</p><p class="gap-evidence">${escapeHtml(gap.evidence)}</p></div>
      <div class="gap-actions"><div class="mastery-meter"><i style="width:${gap.mastery}%"></i></div><small>${t("mastery_review", { mastery: gap.mastery, date: new Date(gap.next_review).toLocaleDateString(i18n.language) })}</small><div class="gap-review-buttons"><button class="mini-button" data-gap="${gap.id}" data-remembered="false">${t("again")}</button><button class="mini-button primary" data-gap="${gap.id}" data-remembered="true">${t("got_it")}</button></div></div>
    </article>`).join("") : `<div class="empty-state"><span>◉</span><h2>${t("radar_clear")}</h2><p>${t("complete_quiz")}</p><a class="button button-primary" href="#dashboard">${t("choose_material")}</a></div>`;
  $$('[data-gap]').forEach(button => button.addEventListener("click", async () => {
    try {
      await api(`/radar/${button.dataset.gap}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remembered: button.dataset.remembered === "true" }),
      });
      toast(button.dataset.remembered === "true" ? t("recall_logged") : t("tomorrow"));
      await renderProofLoop();
    } catch (error) {
      toast(error.message);
    }
  }));
}

const fileInput = $("#file-input");
const dropzone = $("#dropzone");
const uploadButton = $("#upload-button");

function showFile(file) {
  if (!file) return;
  const extension = file.name.toLowerCase().split(".").pop();
  if (!supportedExtensions.includes(extension)) {
    fileInput.value = "";
    toast(t("invalid_type"));
    return;
  }
  if (file.size > 25 * 1024 * 1024) {
    fileInput.value = "";
    toast(t("too_large"));
    return;
  }
  $("#selected-file").hidden = false;
  $("#selected-file").innerHTML = `<strong>${escapeHtml(file.name)}</strong> · ${(file.size / 1024 / 1024).toFixed(2)} MB · ${extension.toUpperCase()}`;
  uploadButton.disabled = false;
}

fileInput.addEventListener("change", () => showFile(fileInput.files[0]));
["dragenter", "dragover"].forEach(event => dropzone.addEventListener(event, e => { e.preventDefault(); dropzone.classList.add("dragging"); }));
["dragleave", "drop"].forEach(event => dropzone.addEventListener(event, e => { e.preventDefault(); dropzone.classList.remove("dragging"); }));
dropzone.addEventListener("drop", event => {
  const file = event.dataTransfer.files[0];
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  showFile(file);
});

$("#upload-form").addEventListener("submit", async event => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  uploadButton.disabled = true;
  $("#progress-panel").hidden = false;
  try {
    state.activeLecture = await api("/lectures", { method: "POST", body: form });
    state.questionIndex = 0;
    state.answers = Array(state.activeLecture.quiz.length).fill(null);
    state.confidences = Array(state.activeLecture.quiz.length).fill(null);
    state.quizSubmitted = false;
    state.quizResult = null;
    state.flashcardIndex = 0;
    state.flashcardRevealed = false;
    await refreshDashboard();
    toast(t("pack_created"));
    location.hash = "summary";
  } catch (error) {
    toast(error.message);
  } finally {
    uploadButton.disabled = false;
    $("#progress-panel").hidden = true;
  }
});

function renderRoadmap(plan) {
  const target = $("#roadmap-plan");
  if (!plan?.items?.length) {
    target.innerHTML = "";
    return;
  }
  target.innerHTML = `<div class="section-heading"><div><p class="eyebrow">${escapeHtml(plan.name)}</p><h2>${t("next_sessions")}</h2></div><span class="quiet-badge">${plan.days} ${t("days_left")}</span></div>` + plan.items.map(item => `
    <article class="plan-day"><strong>${escapeHtml(item.day)}</strong><p>${escapeHtml(item.title)}</p><span>${escapeHtml(item.task)}</span></article>`).join("");
}

function renderSavedRoadmap() {
  const saved = JSON.parse(localStorage.getItem("studycloud-roadmap") || "null");
  if (saved) {
    $("#exam-name").value = saved.name;
    $("#exam-date").value = saved.date;
  }
  renderRoadmap(saved);
}

$("#roadmap-form").addEventListener("submit", event => {
  event.preventDefault();
  const name = $("#exam-name").value.trim();
  const date = $("#exam-date").value;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exam = new Date(`${date}T00:00:00`);
  const days = Math.ceil((exam - today) / 86400000);
  if (!date || days < 1) {
    toast(t("future_date"));
    return;
  }
  const source = state.lectures.length ? state.lectures : [{ title: t("upload_first_lecture") }];
  const sessions = Math.min(Math.max(days, 3), 9);
  const items = Array.from({ length: sessions }, (_, index) => {
    const sessionDate = new Date(today.getTime() + Math.round((index + 1) * days / (sessions + 1)) * 86400000);
    const lecture = source[index % source.length];
    return {
      day: sessionDate.toLocaleDateString(i18n.language, { month: "short", day: "numeric" }),
      title: lecture.title,
      task: index === sessions - 1 ? t("final_mixed") : index % 3 === 1 ? t("weak_concepts") : index % 3 === 2 ? t("flashcard_recall") : t("summary_quiz"),
    };
  });
  const plan = { name, date, days, items };
  localStorage.setItem("studycloud-roadmap", JSON.stringify(plan));
  renderRoadmap(plan);
  toast(t("roadmap_saved"));
});

async function applyLanguage(language) {
  if (state.activeRecognition) state.activeRecognition.stop();
  i18n.apply(language);
  $("#language-select").value = i18n.language;
  $("#auth-language-select").value = i18n.language;
  syncVoiceButtons();
  selectAuthMode($("#register-form").hidden ? "login" : "register");
  if (state.user) {
    await refreshDashboard();
    route();
    if (state.activeLecture) {
      renderSummary();
      renderQuiz();
    }
  }
}

async function start() {
  i18n.apply(i18n.language);
  $("#language-select").value = i18n.language;
  $("#auth-language-select").value = i18n.language;
  $("#language-select").addEventListener("change", event => { applyLanguage(event.target.value).catch(error => toast(error.message)); });
  $("#auth-language-select").addEventListener("change", event => { applyLanguage(event.target.value).catch(error => toast(error.message)); });
  $("#show-login").addEventListener("click", () => selectAuthMode("login"));
  $("#show-register").addEventListener("click", () => selectAuthMode("register"));
  $("#login-form").addEventListener("submit", event => {
    event.preventDefault();
    submitAuth(event.currentTarget, "/auth/login", {
      username: $("#login-username").value.trim(),
      password: $("#login-password").value,
    });
  });
  $("#register-form").addEventListener("submit", event => {
    event.preventDefault();
    submitAuth(event.currentTarget, "/auth/register", {
      full_name: $("#register-name").value.trim(),
      username: $("#register-username").value.trim(),
      email: $("#register-email").value.trim(),
      password: $("#register-password").value,
    });
  });
  $("#profile-toggle").addEventListener("click", () => { $("#profile-menu").hidden = !$("#profile-menu").hidden; });
  $("#logout-button").addEventListener("click", () => showAuth(t("signed_out")));
  document.addEventListener("click", event => {
    if (!event.target.closest(".profile-control")) $("#profile-menu").hidden = true;
  });
  const futureDate = new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10);
  $("#exam-date").min = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  $("#exam-date").value = futureDate;
  window.addEventListener("hashchange", route);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    showAuth();
    return;
  }
  try {
    showWorkspace(await api("/auth/me"));
    await refreshDashboard();
    route();
  } catch (error) {
    showAuth(error.message === "Not authenticated" || error.message === "Could not validate credentials" ? t("session_expired") : error.message);
  }
}

start();
