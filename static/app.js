const state = {
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
};

const routes = {
  dashboard: ["Your study workspace", "Dashboard"],
  upload: ["Add course material", "Upload lecture"],
  summary: ["Review the essentials", "AI summary"],
  quiz: ["Test your recall", "Practice quiz"],
  proofloop: ["Repair weak knowledge", "ProofLoop radar"],
  roadmap: ["Plan the next session", "Exam roadmap"],
};

const supportedExtensions = ["pdf", "pptx", "docx", "txt", "md"];
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[character]));

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { cache: "no-store", ...options });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Something went wrong");
  return body;
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
  $("#page-eyebrow").textContent = routes[current][0];
  $("#page-title").textContent = routes[current][1];
  document.title = `${routes[current][1]} · StudyCloud AI`;
  if (current === "summary") renderSummary();
  if (current === "quiz") renderQuiz();
  if (current === "proofloop") renderProofLoop();
  if (current === "roadmap") renderSavedRoadmap();
  window.scrollTo({ top: 0, behavior: "auto" });
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value || 0);
}

function unitLabel(lecture) {
  if (lecture.file_type === "PPTX") return lecture.pages === 1 ? "slide" : "slides";
  if (lecture.file_type === "PDF") return lecture.pages === 1 ? "page" : "pages";
  return lecture.pages === 1 ? "section" : "sections";
}

async function refreshDashboard() {
  const [stats, lectures, radar] = await Promise.all([api("/stats"), api("/lectures"), api("/radar")]);
  state.lectures = lectures;
  state.radar = radar;
  $("#metrics").innerHTML = [
    ["Materials", stats.lectures, "▤"],
    ["Words analyzed", formatNumber(stats.words), "Aa"],
    ["Quizzes", stats.quizzes, "?"],
    ["Accuracy", `${stats.accuracy}%`, "◎"],
    ["Knowledge debts", stats.blind_spots ? `${stats.open_gaps} · ${stats.blind_spots} blind` : stats.open_gaps, "◉"],
  ].map(([label, value, icon]) => `<article class="metric"><i>${icon}</i><span>${label}</span><strong>${value}</strong></article>`).join("");

  renderLectureList(lectures);
}

function renderLectureList(lectures) {
  $("#lecture-list").innerHTML = lectures.length ? lectures.map(lecture => `
    <article class="lecture-row">
      <div class="lecture-icon">${escapeHtml(lecture.file_type || "FILE")}</div>
      <div class="lecture-info"><h3>${escapeHtml(lecture.title)}</h3><p>${lecture.pages} ${unitLabel(lecture)} · ${formatNumber(lecture.word_count)} words · ${escapeHtml(lecture.engine)}</p></div>
      <div class="lecture-actions">
        <button class="mini-button primary" data-summary="${lecture.id}">Study pack</button>
        <button class="mini-button" data-quiz="${lecture.id}">Practice quiz</button>
      </div>
    </article>`).join("") : `<div class="empty-state"><span>⇧</span><h2>Your library is empty</h2><p>Upload your first course file to begin.</p></div>`;

  $$('[data-summary]').forEach(button => button.addEventListener("click", () => openLecture(button.dataset.summary, "summary")));
  $$('[data-quiz]').forEach(button => button.addEventListener("click", () => openLecture(button.dataset.quiz, "quiz")));
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
  $("#summary-meta").innerHTML = `<span>${escapeHtml(lecture.file_type)} · ${lecture.pages} ${unitLabel(lecture)}</span><span>${formatNumber(lecture.word_count)} words</span><span>${escapeHtml(lecture.engine)}</span>`;
  $("#summary-text").textContent = lecture.summary;
  $("#engine-note").textContent = `Generated with ${lecture.engine}. Important claims remain traceable to the uploaded source.`;
  $("#key-ideas").innerHTML = lecture.key_ideas.map(idea => `<li>${escapeHtml(idea)}</li>`).join("");
  $("#export-link").href = `/api/lectures/${lecture.id}/export`;
  $("#edit-title").value = lecture.title;
  $("#edit-summary").value = lecture.summary;
  $("#edit-ideas").value = lecture.key_ideas.join("\n");
  renderFlashcard();
}

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
    toast("Study pack updated.");
  } catch (error) {
    toast(error.message);
  }
});

function renderFlashcard() {
  const cards = state.activeLecture?.flashcards || [];
  const stage = $("#flashcard-stage");
  $("#flashcard-count").textContent = cards.length ? `${state.flashcardIndex + 1} / ${cards.length}` : "0 cards";
  if (!cards.length) {
    stage.innerHTML = "<strong>No flashcards</strong><p>This material did not provide enough distinct concepts.</p>";
    return;
  }
  const card = cards[state.flashcardIndex];
  stage.innerHTML = state.flashcardRevealed
    ? `<span>Answer · ${escapeHtml(card.source_ref || "Source")}</span><p>${escapeHtml(card.back)}</p>`
    : `<span>Recall before revealing</span><strong>${escapeHtml(card.front)}</strong>`;
  $("#flip-card").textContent = state.flashcardRevealed ? "Show prompt" : "Reveal answer";
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
  result.innerHTML = "Searching the source…";
  try {
    const response = await api(`/lectures/${state.activeLecture.id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const evidence = response.sources.map(source => `<div class="source-evidence"><strong>${escapeHtml(source.ref)}</strong>${escapeHtml(source.text)}</div>`).join("");
    result.innerHTML = `<strong>Answer from your material</strong>${escapeHtml(response.answer)}${evidence}`;
  } catch (error) {
    result.textContent = error.message;
  }
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const voiceDefenseButton = $("#voice-defense");
if (!SpeechRecognition) {
  voiceDefenseButton.disabled = true;
  voiceDefenseButton.textContent = "Dictation unavailable";
}

voiceDefenseButton.addEventListener("click", () => {
  if (!SpeechRecognition) return;
  const recognition = new SpeechRecognition();
  recognition.lang = navigator.language || "en-US";
  recognition.interimResults = false;
  recognition.continuous = true;
  voiceDefenseButton.disabled = true;
  voiceDefenseButton.textContent = "Listening…";
  recognition.onresult = event => {
    const transcript = [...event.results].map(result => result[0].transcript).join(" ");
    const input = $("#defense-input");
    input.value = `${input.value} ${transcript}`.trim();
  };
  recognition.onerror = event => toast(`Dictation stopped: ${event.error}`);
  recognition.onend = () => {
    voiceDefenseButton.disabled = false;
    voiceDefenseButton.textContent = "Start dictation";
  };
  recognition.start();
});

$("#defense-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.activeLecture) return;
  const result = $("#defense-result");
  result.hidden = false;
  result.innerHTML = "Evaluating concept coverage…";
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
      ? `<p><strong>${response.blind_spots.length} confidence trap${response.blind_spots.length === 1 ? "" : "s"} detected.</strong> These omissions were added to ProofLoop with extra priority.</p>`
      : "";
    const evidence = response.sources.map(source => `<div class="source-evidence"><strong>${escapeHtml(source.ref)}</strong>${escapeHtml(source.text)}</div>`).join("");
    result.innerHTML = `<div class="defense-score"><strong>${response.coverage}%</strong><span>concept coverage at ${response.confidence}% confidence</span></div><p>${escapeHtml(response.feedback)}</p>${blindSpotText}<div class="concept-chips">${covered}${missing}</div><p><strong>Next prompt:</strong> ${escapeHtml(response.next_prompt)}</p>${evidence}`;
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
  $("#question-label").textContent = `Question ${index + 1} of ${quiz.length} · ${question.concept || "key concept"}`;
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
  explanation.innerHTML = state.quizSubmitted ? `<strong>Evidence · ${escapeHtml(question.source_ref || "Source")}</strong><br>${escapeHtml(question.explanation)}` : "";
  const result = $("#quiz-result");
  result.hidden = !state.quizSubmitted;
  if (state.quizSubmitted && state.quizResult) {
    const gaps = state.quizResult.knowledge_gaps.length;
    const blind = state.quizResult.blind_spots.length;
    result.innerHTML = `<strong>${state.quizResult.score} / ${state.quizResult.total} correct</strong>${gaps ? `${gaps} knowledge ${gaps === 1 ? "debt was" : "debts were"} added to ProofLoop.` : "No new knowledge debts. Your review intervals increased."}${blind ? ` BlindSpot Detector found ${blind} high-confidence ${blind === 1 ? "mistake" : "mistakes"}.` : ""}`;
  }
  $("#previous-question").disabled = index === 0;
  const next = $("#next-question");
  next.textContent = index === quiz.length - 1 ? (state.quizSubmitted ? "Open ProofLoop" : "Finish quiz") : "Next question →";
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
    toast("Choose an answer before continuing.");
    return;
  }
  if (state.confidences[state.questionIndex] === null) {
    toast("Rate your confidence before continuing.");
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
    toast(`Quiz complete: ${state.quizResult.score} / ${state.quizResult.total}`);
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
    ["Active knowledge debts", active.length],
    ["Confidence traps", blindSpots],
    ["Due for review", due],
    ["Concepts tracked", gaps.length],
  ].map(([label, value]) => `<article class="radar-stat"><span>${label}</span><strong>${value}</strong></article>`).join("");
  $("#gap-list").innerHTML = gaps.length ? gaps.map(gap => `
    <article class="gap-card">
      <div>${gap.is_blind_spot ? `<span class="blindspot-badge">Confidence trap · ${gap.last_confidence}% sure</span>` : ""}<p class="eyebrow">${escapeHtml(gap.lecture_title)} · ${escapeHtml(gap.source_ref)}</p><h3>${escapeHtml(gap.concept)}</h3><p>Mistakes ${gap.mistakes} · successful recalls ${gap.successes}</p><p class="gap-evidence">${escapeHtml(gap.evidence)}</p></div>
      <div class="gap-actions"><div class="mastery-meter"><i style="width:${gap.mastery}%"></i></div><small>${gap.mastery}% mastery · review ${new Date(gap.next_review).toLocaleDateString()}</small><div class="gap-review-buttons"><button class="mini-button" data-gap="${gap.id}" data-remembered="false">Again</button><button class="mini-button primary" data-gap="${gap.id}" data-remembered="true">Got it</button></div></div>
    </article>`).join("") : `<div class="empty-state"><span>◉</span><h2>Your radar is clear</h2><p>Complete a quiz and ProofLoop will map weak concepts here.</p><a class="button button-primary" href="#dashboard">Choose material</a></div>`;
  $$('[data-gap]').forEach(button => button.addEventListener("click", async () => {
    try {
      await api(`/radar/${button.dataset.gap}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remembered: button.dataset.remembered === "true" }),
      });
      toast(button.dataset.remembered === "true" ? "Recall logged. The next interval is longer." : "Scheduled again for tomorrow.");
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
    toast("Choose PDF, PPTX, DOCX, TXT, or MD.");
    return;
  }
  if (file.size > 25 * 1024 * 1024) {
    fileInput.value = "";
    toast("The file is larger than 25 MB.");
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
    toast("Evidence-backed study pack created.");
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
  target.innerHTML = `<div class="section-heading"><div><p class="eyebrow">${escapeHtml(plan.name)}</p><h2>Your next sessions</h2></div><span class="quiet-badge">${plan.days} days left</span></div>` + plan.items.map(item => `
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
    toast("Choose a future exam date.");
    return;
  }
  const source = state.lectures.length ? state.lectures : [{ title: "Upload your first lecture" }];
  const sessions = Math.min(Math.max(days, 3), 9);
  const items = Array.from({ length: sessions }, (_, index) => {
    const sessionDate = new Date(today.getTime() + Math.round((index + 1) * days / (sessions + 1)) * 86400000);
    const lecture = source[index % source.length];
    return {
      day: sessionDate.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      title: lecture.title,
      task: index === sessions - 1 ? "Final mixed quiz" : index % 3 === 1 ? "ProofLoop weak concepts" : index % 3 === 2 ? "Flashcard recall" : "Summary + practice quiz",
    };
  });
  const plan = { name, date, days, items };
  localStorage.setItem("studycloud-roadmap", JSON.stringify(plan));
  renderRoadmap(plan);
  toast("Roadmap saved in this browser.");
});

async function start() {
  const futureDate = new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10);
  $("#exam-date").min = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  $("#exam-date").value = futureDate;
  window.addEventListener("hashchange", route);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  try {
    await refreshDashboard();
    route();
  } catch (error) {
    toast(`API unavailable: ${error.message}`);
  }
}

start();
