const cards = [
  {
    question: "Когда ведомый сервер становится кандидатом?",
    answer: "Когда он перестаёт получать сигналы от лидера и истекает тайм-аут.",
    page: 4,
  },
  {
    question: "Что нужно кандидату, чтобы стать лидером?",
    answer: "Получить голоса большинства серверов.",
    page: 7,
  },
  {
    question: "Когда запись считается зафиксированной?",
    answer: "После того как запись сохранило большинство серверов.",
    page: 9,
  },
];

const cardQuestion = document.querySelector("#card-question");
const cardAnswer = document.querySelector("#card-answer");
const cardSource = document.querySelector("#card-source");
const cardCount = document.querySelector("#card-count");
const revealCard = document.querySelector("#reveal-card");
let cardIndex = 0;

function showCard(showAnswer = false) {
  const card = cards[cardIndex];
  cardQuestion.textContent = card.question;
  cardAnswer.textContent = card.answer;
  cardSource.textContent = `Стр. ${card.page}`;
  cardSource.href = `#source-${card.page}`;
  cardCount.textContent = `${cardIndex + 1} / ${cards.length}`;
  cardAnswer.hidden = !showAnswer;
  cardSource.hidden = !showAnswer;
  revealCard.textContent = showAnswer ? "Скрыть ответ" : "Показать ответ";
  revealCard.setAttribute("aria-expanded", String(showAnswer));
}

function changeCard(direction) {
  cardIndex = (cardIndex + cards.length + direction) % cards.length;
  showCard();
}

document.querySelector("#previous-card").addEventListener("click", () => changeCard(-1));
document.querySelector("#next-card").addEventListener("click", () => changeCard(1));
revealCard.addEventListener("click", () => showCard(cardAnswer.hidden));
showCard();

const quizForm = document.querySelector("#quiz-form");
const questions = Array.from(quizForm.querySelectorAll("fieldset"));
const quizScore = document.querySelector("#quiz-score");
const resetQuiz = document.querySelector("#reset-quiz");
const checkQuiz = quizForm.querySelector('button[type="submit"]');

quizForm.addEventListener("submit", event => {
  event.preventDefault();
  let score = 0;
  for (const question of questions) {
    const correct = question.querySelector("input:checked").value === question.dataset.answer;
    if (correct) score += 1;

    const feedback = question.querySelector(".feedback");
    feedback.querySelector(".result-label")?.remove();
    const label = document.createElement("strong");
    label.className = "result-label";
    label.textContent = correct ? "Верно. " : "Неверно. ";
    feedback.prepend(label);
    question.dataset.result = correct ? "correct" : "incorrect";
    feedback.hidden = false;
    question.disabled = true;
  }
  quizScore.textContent = `Верных ответов: ${score} из ${questions.length}`;
  resetQuiz.hidden = false;
  checkQuiz.disabled = true;
});

quizForm.addEventListener("reset", () => {
  for (const question of questions) {
    question.querySelector(".feedback").hidden = true;
    delete question.dataset.result;
    question.disabled = false;
  }
  quizScore.textContent = "";
  resetQuiz.hidden = true;
  checkQuiz.disabled = false;
  questions[0].querySelector("input").focus();
});

function openSource() {
  const source = document.getElementById(location.hash.slice(1));
  if (source instanceof HTMLDetailsElement) source.open = true;
}

window.addEventListener("hashchange", openSource);
openSource();
