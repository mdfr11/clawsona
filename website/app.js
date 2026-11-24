"use strict";

const translations = {
  ru: {
    skip: "К содержимому",
    nav_demo: "Разговор",
    nav_how: "Как устроено",
    get_started: "Начать",
    eyebrow: "ОТКРЫТЫЙ КОД · НА ОСНОВЕ OPENCLAW",
    hero_title: "Дай своему<br>OpenClaw<br><em>голос.</em>",
    hero_description:
      "Маленький компьютер. Знакомый голос. Собеседник, с которым можно подумать вслух, научиться новому и пользоваться инструментами OpenClaw.",
    hear_it: "Послушать голос",
    hero_note: "Локальная речь · Русский и английский · Любое имя",
    visual_label: "Голос с небольшим характером.",
    you: "ТЫ",
    hero_user: "«Мира, давай поговорим».",
    hero_reply: "«Конечно. О чём думаешь?»",
    visual_caption: "Пример диалога. Имя выбираешь ты.",
    principle_1: "Речь обрабатывается рядом.",
    principle_1_text: "Whisper распознаёт локально. Piper озвучивает локально.",
    principle_2: "За общение отвечает OpenClaw.",
    principle_2_text: "Один агент для контекста, модели и инструментов.",
    principle_3: "Свой голос и своё имя.",
    principle_3_text: "Своё имя. Свой голос. Свой темп.",
    conversation_kicker: "МЕНЬШЕ ПЕЧАТАТЬ. БОЛЬШЕ ГОВОРИТЬ.",
    conversation_title: "Позови по имени.<br>Продолжай разговор.",
    conversation_description:
      "Не нужно обращаться по имени перед каждой мыслью. Позови один раз, обсуди идею, научись новому или попроси воспользоваться подключённым инструментом.",
    tab_talk: "Поговорить",
    tab_learn: "Английский",
    tab_weather: "Узнать о мире",
    tab_music: "Музыка и дела",
    illustration_note: "Иллюстрация диалога, без подключения к модели.",
    listen_title: "А вот голос настоящий. Послушай.",
    sample_note:
      "Реальные сэмплы ElevenLabs, созданные из публичного текста. Можно использовать и локальный Piper. Эта страница не запрашивает доступ к микрофону.",
    how_kicker: "МАЛЕНЬКИЙ КОМПЬЮТЕР. ПОНЯТНАЯ АРХИТЕКТУРА.",
    how_title: "Голос — ClawSona.<br>За диалогом — OpenClaw.",
    how_description:
      "ClawSona управляет микрофоном, распознаванием и озвучкой. OpenClaw ведёт разговор и выбирает инструменты. У каждой части своя задача.",
    pipeline_local: "НА ТВОЁМ УСТРОЙСТВЕ",
    pipeline_1: "Твой голос",
    pipeline_1_text: "Silero находит речь.<br>Whisper превращает её в текст.",
    pipeline_agent: "АГЕНТ",
    pipeline_2_text: "Контекст, запросы к модели<br>и вызовы инструментов.",
    pipeline_model: "По умолчанию: DeepSeek API",
    pipeline_reply: "СНОВА В ДИНАМИКАХ",
    pipeline_3: "Ответ вслух",
    pipeline_3_text:
      "Локальный Piper на двух языках.<br>Или ElevenLabs по желанию.",
    data_note:
      "Распознавание работает локально. Текст запросов отправляется выбранной модели. OpenClaw сохраняет историю сессий. При облачной озвучке текст ответа отправляется её провайдеру.",
    start_kicker: "СЛЕДУЮЩИЙ РАЗГОВОР НАЧИНАЕТСЯ ЗДЕСЬ.",
    start_title: "Возьми мини-ПК.<br>Придумай ему имя.",
    start_description:
      "Начни с локальной речи и официального API DeepSeek через OpenClaw. Дополнительная подписка на голос не нужна.",
    requirements_title: "Что понадобится",
    requirements:
      "Python 3.11–3.13, uv, OpenClaw, микрофон и динамики. Целевые платформы — Linux и macOS.",
    provider_note:
      "Код бесплатный. Облачная модель и необязательные голосовые API оплачиваются отдельно.",
    download_source: "Скачать исходники · v0.3.0",
    view_github: "Открыть GitHub",
    setup_1: "Подготовь проект",
    setup_once: "ОДИН РАЗ",
    setup_1_note:
      "Распакуй исходники и открой терминал в этой папке. Установи PortAudio: libportaudio2 на Debian/Ubuntu или brew install portaudio на macOS.",
    setup_2: "Выбери имя",
    setup_2_note:
      "Добавь свой ключ DeepSeek API в .env. Затем укажи имя и необязательные варианты написания:",
    setup_3: "Подготовь модели. Начинай говорить.",
    setup_run: "ЗАПУСК",
    setup_3_note:
      "Установи OpenClaw по официальной инструкции. Подготовка создаст отдельный профиль и один раз скачает речевые модели.",
    openclaw_install: "Инструкция по установке OpenClaw",
    copy: "Копировать",
    faq_kicker: "ПОЛЕЗНО ЗНАТЬ",
    faq_title: "Несколько честных ответов.",
    faq_1_q: "Всё работает без интернета?",
    faq_1_a:
      "Whisper и Piper работают локально после загрузки моделей. DeepSeek, погода и поиск требуют интернет. В прямом режиме Ollama можно использовать локальную модель, но без инструментов OpenClaw.",
    faq_2_q: "Можно перебить ответ?",
    faq_2_a:
      "Да: обратись по настроенному имени во время ответа и продолжай вопрос. После подтверждения обращения голос остановится. Для наушников есть режим прерывания любой фразой. Полноценного акустического эхоподавления нет: громкие колонки и наложение голосов могут мешать распознаванию.",
    faq_3_q: "Подойдёт любой мини-ПК?",
    faq_3_a:
      "Важны процессор, расположение микрофона и шум. Стартовая настройка — Whisper small на четырёх потоках CPU. Проверь живой диалог на своём устройстве и подбери модель, голос и длину паузы. Одинаковая задержка на всех устройствах не обещается.",
    faq_4_q: "А музыка и другие действия?",
    faq_4_a:
      "Погода и поиск доступны через ограниченные инструменты. Яндекс Музыка экспериментальная, по умолчанию отключена и ещё не проверена от начала до конца. В создаваемом профиле не включены shell и произвольный доступ к файлам.",
    faq_5_q: "ClawSona бесплатная и открытая?",
    faq_5_a:
      "Код распространяется под GPL-3.0-or-later: его можно бесплатно использовать, изменять и распространять с соблюдением лицензии. У библиотек и голосовых моделей свои условия. Платные API и подписки оплачиваются отдельно.",
    closing: "Немного человечнее.<br>Гораздо ближе тебе.",
    footer_note:
      "Независимый проект на основе OpenClaw. Делимся открыто и продолжаем развивать.",
  },
};
const original = new Map();
document
  .querySelectorAll("[data-i18n], [data-i18n-html]")
  .forEach((el) => original.set(el, el.innerHTML));
let language = "en";
let scenario = "talk";
try {
  if (localStorage.getItem("clawsona-language") === "ru") language = "ru";
} catch {}

const scenes = {
  en: {
    talk: {
      audio: "en",
      messages: [
        ["user", "Mira, hello."],
        ["assistant", "Hello! I'm Mira. What would you like to do today?"],
        ["follow-up", "Why is the sky blue?"],
        ["assistant", "Let's break it down with a simple example about light."],
      ],
    },
    learn: {
      audio: "en",
      messages: [
        ["user", "Mira, teach me a little Spanish."],
        [
          "assistant",
          "Let's start with a greeting: buenos días means good morning.",
        ],
        ["follow-up", "And how do I say thank you?"],
        ["assistant", "Gracias. Would you like to try a short conversation?"],
      ],
    },
    weather: {
      audio: "en",
      messages: [
        ["user", "Mira, what's the weather in Paris?"],
        ["tool", "clawsona_weather · Paris"],
        ["assistant", "I'll check the current forecast."],
        ["follow-up", "Will I need an umbrella tomorrow?"],
      ],
    },
    music: {
      audio: "en",
      messages: [
        ["user", "Mira, play some jazz."],
        ["tool", "clawsona_music · optional integration"],
        [
          "assistant",
          "Music controls are available when the integration is connected.",
        ],
        ["follow-up", "What else can we do?"],
        [
          "assistant",
          "Ask about the world, learn something new, or use the tools you connect to OpenClaw.",
        ],
      ],
    },
  },
  ru: {
    talk: {
      audio: "ru",
      messages: [
        ["user", "Мира, привет."],
        ["assistant", "Привет! Я Мира. Давай поговорим."],
        ["follow-up", "Объясни, почему небо голубое."],
        ["assistant", "Давай разберёмся на простом примере со светом."],
      ],
    },
    learn: {
      audio: "en",
      messages: [
        ["user", "Mira, can we practice English?"],
        ["assistant", "Of course. Tell me about your day."],
        ["follow-up", "I went for a walk today."],
        ["assistant", "That sounds nice! Where did you go?"],
      ],
    },
    weather: {
      audio: "ru",
      messages: [
        ["user", "Мира, какая погода в Париже?"],
        ["tool", "clawsona_weather · Paris"],
        ["assistant", "Я уточню актуальный прогноз."],
        ["follow-up", "А завтра понадобится зонт?"],
      ],
    },
    music: {
      audio: "ru",
      messages: [
        ["user", "Мира, включи джаз."],
        ["tool", "clawsona_music · необязательная интеграция"],
        [
          "assistant",
          "Управление музыкой доступно, когда интеграция подключена.",
        ],
        ["follow-up", "А что ещё можно сделать?"],
        [
          "assistant",
          "Узнавать о мире, учиться новому и пользоваться инструментами, которые ты подключишь к OpenClaw.",
        ],
      ],
    },
  },
};

function renderScene() {
  const data = scenes[language][scenario];
  const messages = document.getElementById("messages");
  messages.replaceChildren();
  for (const [role, text] of data.messages) {
    if (role === "tool") {
      const note = document.createElement("div");
      note.className = "tool-note";
      note.textContent = text;
      messages.append(note);
      continue;
    }
    const row = document.createElement("div");
    row.className = `message ${role === "assistant" ? "assistant" : role}`;
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent =
      role === "assistant" ? "C" : language === "ru" ? "Т" : "Y";
    const body = document.createElement("div");
    body.className = "message-body";
    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent =
      role === "assistant" ? "MIRA" : language === "ru" ? "ТЫ" : "YOU";
    if (role === "follow-up")
      label.dataset.note =
        language === "ru" ? "без повторного имени" : "no name needed";
    const content = document.createElement("p");
    content.textContent = text;
    content.lang = data.audio;
    body.append(label, content);
    row.append(avatar, body);
    messages.append(row);
  }
  document.querySelectorAll("[data-scenario]").forEach((tab) => {
    const active = tab.dataset.scenario === scenario;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document
    .getElementById("dialogue")
    .setAttribute("aria-labelledby", `tab-${scenario}`);
  document.getElementById("sample-language").textContent =
    data.audio === "ru" ? "РУССКИЙ" : "ENGLISH";
  const note = document.getElementById("scenario-note");
  note.hidden = scenario !== "music";
  note.textContent =
    language === "ru"
      ? "Яндекс Музыка — экспериментальная интеграция. Нужны настройка и аккаунт; в этом примере ничего не воспроизводится."
      : "Yandex Music is experimental. Setup and an account are required; this example does not start music playback.";
  const voice = document.getElementById("voice-sample");
  const path = `media/hello-${data.audio}.mp3`;
  if (voice.getAttribute("src") !== path) {
    voice.pause();
    voice.setAttribute("src", path);
    voice.load();
  }
  document.getElementById("voice-description").textContent =
    language === "ru"
      ? data.audio === "ru"
        ? "ElevenLabs · Roger · русский"
        : "ElevenLabs · Roger · английский"
      : data.audio === "ru"
        ? "ElevenLabs · Roger · Russian"
        : "ElevenLabs · Roger · English";
}

function applyLanguage() {
  document.documentElement.lang = language;
  document.querySelectorAll("[data-i18n], [data-i18n-html]").forEach((el) => {
    const key = el.dataset.i18n || el.dataset.i18nHtml;
    if (language === "en") el.innerHTML = original.get(el);
    else if (translations.ru[key]) {
      if (
        el.hasAttribute("data-i18n-html") ||
        translations.ru[key].includes("<br>")
      )
        el.innerHTML = translations.ru[key];
      else el.textContent = translations.ru[key];
    }
  });
  const toggle = document.getElementById("language");
  toggle.innerHTML =
    language === "ru" ? "RU <span>/ EN</span>" : "EN <span>/ RU</span>";
  toggle.setAttribute(
    "aria-label",
    language === "ru" ? "Switch to English" : "Переключить на русский",
  );
  document.title =
    language === "ru"
      ? "ClawSona — Дай своему OpenClaw голос."
      : "ClawSona — Give your OpenClaw a voice.";
  renderScene();
}

document.getElementById("language").addEventListener("click", () => {
  language = language === "en" ? "ru" : "en";
  try {
    localStorage.setItem("clawsona-language", language);
  } catch {}
  applyLanguage();
});
document.querySelectorAll("[data-scenario]").forEach((tab) => {
  tab.addEventListener("click", () => {
    scenario = tab.dataset.scenario;
    renderScene();
  });
  tab.addEventListener("keydown", (event) => {
    const tabs = [...document.querySelectorAll("[data-scenario]")];
    const index = tabs.indexOf(tab);
    let next;
    if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
    if (event.key === "ArrowLeft")
      next = tabs[(index - 1 + tabs.length) % tabs.length];
    if (event.key === "Home") next = tabs[0];
    if (event.key === "End") next = tabs[tabs.length - 1];
    if (next) {
      event.preventDefault();
      scenario = next.dataset.scenario;
      renderScene();
      next.focus();
    }
  });
});

document.querySelectorAll("[data-copy]").forEach((button) =>
  button.addEventListener("click", async () => {
    const text = document.getElementById(button.dataset.copy).textContent;
    const message = document.getElementById("status");
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      button.textContent = language === "ru" ? "Готово" : "Copied";
      message.textContent =
        language === "ru" ? "Команды скопированы." : "Commands copied.";
      setTimeout(() => {
        button.textContent = language === "ru" ? "Копировать" : "Copy";
      }, 1800);
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(document.getElementById(button.dataset.copy));
      selection.removeAllRanges();
      selection.addRange(range);
      message.textContent =
        language === "ru"
          ? "Текст выделен. Нажмите Ctrl+C или Cmd+C."
          : "Text selected. Press Ctrl+C or Cmd+C.";
    }
  }),
);

fetch("site-config.json")
  .then((response) => {
    if (!response.ok) throw new Error("No site configuration");
    return response.json();
  })
  .then((config) => {
    if (
      config.repository_url &&
      /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(config.repository_url)
    ) {
      document.querySelectorAll("[data-repo-url]").forEach((link) => {
        link.href = config.repository_url;
        link.hidden = false;
      });
    }
  })
  .catch(() => {});

applyLanguage();
