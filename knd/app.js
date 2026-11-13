const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
// Keep short prepositions and system abbreviations with the next word on screen.
const glue = value => String(value ?? '')
  .replace(/(?<=^|[\s(«])(в|во|и|с|со|к|ко|о|об|от|у|а|на|по|за|из|до|не|для|без|при)\s+/giu, '$1\u00a0')
  .replace(/(?<=^|[\s(«])(АСУ|ГИС|ТОР|ГАС|МП)\s+/gu, '$1\u00a0')
  .replace(/(?<=[А-Яа-яЁёA-Za-z])-(?=[А-Яа-яЁёA-Za-z])/g, '\u2011')
  .replace(/(?<=\d) (?=\d{3}(?!\d))/g, '\u00a0')
  // Keep a short last word with the previous one, but leave two-word labels breakable.
  .replace(/ (?=[^ ]{1,10}$)/u, (space, offset, text) => text.split(' ').length > 2 ? '\u00a0' : space);
const html = value => escapeHTML(glue(value));
const draft = location.search.includes('draft');
const stage = $('#stage');
const video = $('#video');
let deck;
let chapter = -1;
let step = 0;
let paused = false;
let black = false;
let elapsed = 0;
let previousTick = performance.now();
let controlTimer;
let lastNav = -1000;
let playbackVersion = 0;
const posterCache = [];

function fit() {
  // Phones report a zoomed-out innerWidth; the client box is the visible viewport.
  const width = document.documentElement.clientWidth || innerWidth;
  const height = document.documentElement.clientHeight || innerHeight;
  stage.style.transform = `translate(-50%,-50%) scale(${Math.min(width / 1920, height / 1080)})`;
}
addEventListener('resize', fit);
fit();

const hasDialog = () => Boolean(document.querySelector('dialog[open]'));
const current = () => deck?.sections[chapter];
const screens = section => section?.extra ? ['Категорирование', 'ИИ-риск-профиль'] : section?.autoLandingSeconds ? ['Сложная схема', 'Единая точка входа'] : [];
const lastStep = section => screens(section).length ? 2 : 1;
function canPlay() { return current()?.video && step === 0 && !paused && !black && !hasDialog() && !document.hidden; }
function syncPlayback() {
  const attempt = ++playbackVersion;
  if (canPlay()) video.play().catch(() => {
    if (attempt === playbackVersion && canPlay()) { paused = true; drawControls(); }
  });
  else video.pause();
}

function drawSummary(section) {
  $('#summary').classList.toggle('compact', Boolean(section.extra) || section.graphic === 'risk-model' || section.metrics.length > 2);
  $('#summary').innerHTML = `<p class="eyebrow">${escapeHTML(section.graphic ? 'Цифровой инструмент' : 'Практика Роструда')}</p>
    <h2>${html(section.tagline)}</h2>
    <ul>${section.bullets.map(text => `<li>${html(text)}</li>`).join('')}</ul>
    ${section.metrics.length ? `<div class="metrics">${section.metrics.map(metric => `<div class="metric"><b>${escapeHTML(metric.value)}</b><span>${html(metric.label)}</span></div>`).join('')}</div>` : ''}
    ${section.asOf ? `<p class="source-date">${html(section.asOf)}</p>` : ''}
    ${section.autoLandingSeconds ? '<button id="show-instructions" class="secondary-action">Открыть инструкции ↗</button>' : ''}
    ${section.extra ? '<button id="show-risk-model" class="secondary-action">Как работает риск-модель ↗</button>' : ''}`;
  $('#show-instructions')?.addEventListener('click', () => go(chapter, 2));
  $('#show-risk-model')?.addEventListener('click', () => go(chapter, 2));
}

function drawGraphic(section) {
  const graphic = $('#graphic');
  graphic.hidden = !section.graphic;
  if (!section.graphic) { graphic.innerHTML = ''; return; }
  if (section.graphic === 'gasu') {
    graphic.innerHTML = `<p class="graphic-kicker">ГАС «Управление»</p><h2>Результаты работы<br>на одном экране</h2><div class="flow">
      <div class="flow-row"><b>01</b><span>Показатели деятельности</span></div>
      <div class="flow-row"><b>02</b><span>Оценка результатов</span></div>
      <div class="flow-row"><b>03</b><span>Методики премирования</span></div></div>`;
  } else if (section.graphic === 'risk-model') {
    graphic.innerHTML = `<p class="graphic-kicker">Машинное обучение · пилот 2026</p><h2>Аналитическая оценка<br>риска нарушений</h2><div class="flow">
      <div class="flow-row"><b>01</b><span>Восемь внутренних источников АСУ КНД</span></div>
      <div class="flow-row"><b>02</b><span>Логистическая регрессия и скоринг</span></div>
      <div class="flow-row"><b>03</b><span>Оценка риска и влияющие признаки</span></div></div>`;
  } else if (section.stats) {
    const stats = section.stats;
    graphic.innerHTML = `<p class="graphic-kicker">Онлайнинспекция.рф · ${escapeHTML(stats.asOf)}</p>
      <div class="online-hero"><div><b>${escapeHTML(stats.hero.value)}</b><span>${html(stats.hero.label)}</span><small>${html(stats.hero.detail)}</small></div>
      <a class="online-link" href="https://онлайнинспекция.рф" target="_blank" rel="noopener noreferrer"><img src="assets/qr-online.svg" alt="QR-код сервиса Онлайнинспекция.рф"><span>Открыть<br>сервис ↗</span></a></div>
      <div class="online-stats">${stats.tiles.map(tile => `<div class="online-stat"><p>${html(tile.service)}</p><b>${escapeHTML(tile.value)}</b><span>${html(tile.label)}</span></div>`).join('')}</div>`;
  } else {
    graphic.innerHTML = `<p class="graphic-kicker">Сервисы для граждан</p><p class="domain">Онлайнинспекция.рф</p><div class="flow">
      <div class="flow-row"><b>01</b><span>Выбрать вопрос</span></div>
      <div class="flow-row"><b>02</b><span>Направить обращение</span></div>
      <div class="flow-row"><b>03</b><span>Получить ответ</span></div></div>
      <a class="online-link" href="https://онлайнинспекция.рф" target="_blank" rel="noopener noreferrer"><img src="assets/qr-online.svg" alt="QR-код сервиса Онлайнинспекция.рф"><span>Открыть сервис ↗</span></a>`;
  }
}

function drawLanding() {
  const landing = deck.landing;
  $('#landing').innerHTML = `<div class="landing-browser"><div class="browser-bar"><i></i><i></i><i></i><span>${escapeHTML(landing.title)}</span></div>
      <div class="browser-view" role="img" aria-label="Страница «${escapeHTML(landing.title)}»" style="background-image:url('${escapeHTML(landing.screenshot)}')"></div></div>
    <div class="landing-side"><p class="graphic-kicker">${escapeHTML(landing.kicker)}</p><h2>${html(landing.title)}</h2><p>${html(landing.lead)}</p>
      <div class="guide-grid">${deck.instructions.map(item => `<figure class="guide-card"><img src="${escapeHTML(item.image)}" alt="Руководство «${escapeHTML(item.title)}»"><figcaption><b>${html(item.title)}</b>${html(item.description)}</figcaption></figure>`).join('')}</div>
      <p class="landing-status">${html(landing.status)}</p></div>
    <div class="creation-process"><strong>Как создаём</strong>${landing.steps.map(text => `<span>${html(text)}</span>`).join('')}</div>`;
}

function drawControls() {
  const section = current();
  const labels = screens(section);
  const screenIndex = step === 2 ? 1 : 0;
  $('#screen-nav').hidden = !labels.length;
  $('#screen-nav').innerHTML = labels.map((label, index) => `<button data-screen="${index === 0 ? (section.video ? 0 : 1) : 2}" ${index === screenIndex ? 'aria-current="step"' : ''}><span>${index + 1} / ${labels.length}</span>${escapeHTML(label)}</button>`).join('');
  $('#screen-nav').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    if (Number(button.dataset.screen) === 2 && step === 2) return;
    go(chapter, Number(button.dataset.screen), Number(button.dataset.screen) === 0);
  }));
  $('#previous').disabled = chapter < 0;
  $('#next').disabled = chapter === deck.sections.length;
  $('#position').textContent = chapter < 0 ? 'Начало' : chapter === deck.sections.length ? 'Финал' : `${chapter + 1} / ${deck.sections.length}${labels.length ? ` · экран ${screenIndex + 1}/${labels.length}` : ''}`;
  $('#next').title = section && step !== 2 && labels.length ? `Далее: ${labels[1]} · →` : 'Следующий раздел · →';
  // Keep the slot so the bar width, and the → button position, stay constant.
  $('#pause').style.visibility = !section || step === 2 || (!section.video && !section.autoLandingSeconds) || (step === 1 && !section.autoLandingSeconds) ? 'hidden' : '';
  $('#pause').textContent = paused ? '▶' : 'Ⅱ';
  $('#pause').setAttribute('aria-label', paused ? 'Продолжить' : 'Приостановить');
  $('#pause').title = `${paused ? 'Продолжить' : 'Пауза'} · P`;
  $('#progress').querySelectorAll('button').forEach((button, index) => {
    button.classList.toggle('current', index === chapter);
    button.classList.toggle('done', index < chapter);
    if (index === chapter) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  });
  $('#page-number').textContent = `${String(chapter + 1).padStart(2, '0')} / ${String(deck.sections.length).padStart(2, '0')}${labels.length ? ` · ${screenIndex + 1}/${labels.length}` : ''}`;
}

function go(index, requestedStep, replay = false) {
  const wasSecondary = step === 2;
  index = Number.isInteger(index) ? Math.max(-1, Math.min(deck.sections.length, index)) : -1;
  const changed = chapter !== index;
  chapter = index;
  const section = current();
  step = section ? Math.min(section.autoLandingSeconds || section.extra ? 2 : 1, Math.max(0, Number(requestedStep) || (section.video ? 0 : 1))) : 0;
  if (section && !section.video) step = 1;
  if (changed || replay) { elapsed = 0; paused = false; }
  else if (wasSecondary && step < 2) elapsed = 0;
  video.pause();
  stage.classList.toggle('cover', chapter < 0);
  stage.classList.toggle('closing', chapter === deck.sections.length);
  $('#cover').hidden = chapter >= 0;
  $('#chapter').hidden = !section;
  $('#closing').hidden = chapter !== deck.sections.length;
  $('#video-error').hidden = true;
  if (section) {
    const screen = step === 2 && section.extra ? section.extra : section;
    const isLanding = step === 2 && Boolean(section.autoLandingSeconds);
    $('#chapter-title').textContent = glue(screen.title);
    $('#chapter-subtitle').textContent = glue(screen.subtitle);
    $('#media-layout').hidden = isLanding;
    $('#landing').hidden = !isLanding;
    $('#still').hidden = !screen.video;
    video.hidden = !screen.video;
    video.classList.toggle('stopped', step !== 0);
    if (section.video) $('#still').src = step === 0 ? section.first : section.poster;
    $('#still').alt = `Кадр раздела «${section.title}»`;
    if (section.video && (changed || replay || video.dataset.section !== section.id)) {
      video.dataset.section = section.id;
      video.poster = section.first;
      video.src = section.video;
      video.load();
    }
    if (section.video && step === 0) video.currentTime = 0;
    drawSummary(screen); drawGraphic(screen);
    $('#media-caption').hidden = section.id !== 'ervk' || step === 2;
    $('#media-caption').textContent = section.id === 'ervk' ? 'Расчёт в АСУ КНД  ·  Подписание  ·  Передача в ЕРВК' : '';
  }
  drawControls();
  const hash = chapter < 0 ? '' : chapter === deck.sections.length ? '#thanks' : `#${section.id}${step === 2 ? '/2' : ''}`;
  history.replaceState(null, '', location.pathname + location.search + hash);
  syncPlayback();
  showControls();
}

function next() {
  if (chapter < 0) return go(0);
  if (chapter >= deck.sections.length) return;
  const section = current();
  if (section.autoLandingSeconds && step < 2) return go(chapter, 2);
  if (section.extra && step < 2) return go(chapter, 2);
  go(chapter + 1);
}
function previous() {
  if (chapter <= -1) return;
  if (chapter === deck.sections.length) return go(chapter - 1, lastStep(deck.sections[chapter - 1]));
  if (step === 2) return go(chapter, 1);
  go(chapter - 1, lastStep(deck.sections[chapter - 1]));
}
function nav(action) {
  const now = performance.now();
  if (now - lastNav < 250) return;
  lastNav = now;
  action();
}

function togglePause() {
  paused = !paused;
  syncPlayback();
  drawControls();
}
function setBlack(value) {
  black = value;
  $('#black').hidden = !value;
  syncPlayback();
}
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else document.documentElement.requestFullscreen().catch(() => {});
}
function showControls() {
  document.body.classList.remove('controls-hidden');
  clearTimeout(controlTimer);
  controlTimer = setTimeout(() => document.body.classList.add('controls-hidden'), 3500);
}

function openDialog(dialog) {
  if (hasDialog()) return;
  dialog.showModal();
  syncPlayback();
}
function openNotes() {
  const section = current();
  const details = section && draft ? `${section.needs.length ? `<div class="pending"><h4>К подготовке финальной версии</h4><ul>${section.needs.map(item => `<li>${escapeHTML(item)}</li>`).join('')}</ul></div>` : ''}
    <p class="source-date">Источники: ${section.sources.map(escapeHTML).join('; ')}</p>` : '';
  const remarks = section?.remarks?.length && draft ? `<div class="remarks"><h4>Для докладчика</h4><ul>${section.remarks.map(item => `<li>${html(item)}</li>`).join('')}</ul></div>` : '';
  $('#speaker-content').innerHTML = section ? `<h3>${chapter + 1}. ${html(section.title)}</h3><p class="cue">${html(section.cue)}</p>${section.notes.map(paragraph => `<p>${html(paragraph)}</p>`).join('')}
    ${remarks}${details}`
    : chapter === deck.sections.length ? `<h3>Заключение</h3><p>${html(deck.outro)}</p>`
    : `<h3>${escapeHTML(deck.title)}</h3><p>${escapeHTML(deck.intro)}</p><p class="cue">После титула сразу начинаются ролики. Стрелки листают экраны, клавиша T открывает разделы, N — текст текущего раздела.</p>`;
  openDialog($('#notes-dialog'));
}

function drawSpeaker() {
  const speaker = deck.speaker || {};
  for (const page of ['cover', 'closing']) {
    $(`#${page}-speaker`).textContent = speaker.name || '';
    $(`#${page}-speaker`).hidden = !speaker.name;
    const position = speaker.position && !/Роструд/.test(speaker.position) ? `${speaker.position}, Роструд` : speaker.position;
    $(`#${page}-position`).textContent = position || deck.organization;
  }
}

function preloadPosters() {
  // A decoded poster paints at once; otherwise <video> shows its previous poster for a frame after load().
  if (typeof Image !== 'function') return;
  for (const section of deck.sections) for (const src of [section.first, section.poster]) {
    if (!src) continue;
    const image = new Image();
    image.src = src;
    image.decode?.().catch(() => {});
    posterCache.push(image);
  }
}

function fromHash() {
  const [id, requested] = location.hash.slice(1).split('/');
  return [id === 'thanks' ? deck.sections.length : deck.sections.findIndex(section => section.id === id), Number(requested)];
}

video.addEventListener('ended', () => {
  const section = current();
  if (!section?.video || step !== 0 || !video.ended || video.dataset.section !== section.id) return;
  // Keep the decoder's final frame visible. Hiding the video while its final
  // JPEG loads briefly reveals the first-frame fallback underneath it.
  step = 1;
  syncPlayback();
  drawControls();
  showControls();
});
video.addEventListener('error', () => {
  if (current()?.video && step === 0 && video.dataset.section === current().id) $('#video-error').hidden = false;
});
$('#retry').addEventListener('click', () => go(chapter, 0, true));
$('#start').addEventListener('click', () => nav(() => go(0)));
$('#restart').addEventListener('click', () => go(-1));
$('#next').addEventListener('click', () => nav(next));
$('#previous').addEventListener('click', () => nav(previous));
$('#pause').addEventListener('click', togglePause);
$('#contents').addEventListener('click', () => openDialog($('#contents-dialog')));
$('#notes').addEventListener('click', openNotes);
$('#fullscreen').addEventListener('click', toggleFullscreen);
$('#black').addEventListener('click', () => setBlack(false));
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', syncPlayback);
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
});
stage.addEventListener('click', event => {
  if (event.detail > 1 || event.target.closest('button,a') || getSelection()?.toString() || !deck) return;
  nav(next);
});
addEventListener('keydown', event => {
  if (!deck || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  const key = event.key;
  if (black) { if (['Escape', ' ', 'Enter', 'ArrowRight', 'ArrowLeft', 'PageDown', 'PageUp', 'b', 'B', '.'].includes(key)) { event.preventDefault(); setBlack(false); } return; }
  if (hasDialog()) return;
  const nextKeys = ['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'];
  const previousKeys = ['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'];
  if (event.target.closest('input,textarea,[contenteditable="true"]')) return;
  if ([' ', 'Enter'].includes(key) && event.target.closest('button,a')) return;
  if (nextKeys.includes(key)) { event.preventDefault(); nav(next); }
  else if (previousKeys.includes(key)) { event.preventDefault(); nav(previous); }
  else if (key === 'Home') { event.preventDefault(); go(-1); }
  else if (key === 'End') { event.preventDefault(); go(deck.sections.length); }
  else if (event.code === 'KeyT') openDialog($('#contents-dialog'));
  else if (event.code === 'KeyN') openNotes();
  else if (event.code === 'KeyR' && current()) go(chapter, 0, true);
  else if (event.code === 'KeyP' && current()) togglePause();
  else if (event.code === 'KeyF' || key === 'F5') { event.preventDefault(); toggleFullscreen(); }
  else if (event.code === 'KeyB' || event.code === 'Period') setBlack(true);
  else if (/^Digit[0-9]$/.test(event.code)) { const index = event.code === 'Digit0' ? 9 : Number(event.code.slice(-1)) - 1; if (index < deck.sections.length) go(index, 0, true); }
});
addEventListener('mousemove', showControls);
addEventListener('touchstart', showControls, {passive:true});
document.addEventListener('fullscreenchange', showControls);
// After a mouse click the button keeps focus, and Space/Enter would press it again instead of advancing.
// Capture phase: blur before a dialog opens, so closing it does not return focus to the button.
document.addEventListener('click', event => { if (event.detail) event.target.closest?.('button')?.blur(); }, true);
document.addEventListener('visibilitychange', () => { previousTick = performance.now(); syncPlayback(); });

function tick(now) {
  const delta = Math.max(0, now - previousTick);
  previousTick = now;
  const section = current();
  if (section?.autoLandingSeconds && step < 2 && !paused && !black && !hasDialog() && !document.hidden) {
    // Count only active time, including the held final frame after the short clip.
    if (step === 1 || (!video.paused && video.readyState >= 2)) elapsed += delta;
    const button = $('#show-instructions');
    const secondsLeft = Math.max(0, Math.ceil(section.autoLandingSeconds - elapsed / 1000));
    if (button) button.textContent = glue(`Инструкции через ${secondsLeft} с ↗`);
    if (elapsed >= section.autoLandingSeconds * 1000) go(chapter, 2);
  }
  requestAnimationFrame(tick);
}

try {
  const response = await fetch('content.json?v=20261113-r6');
  if (!response.ok) throw new Error('content unavailable');
  deck = await response.json();
  drawLanding();
  $('#contents-list').innerHTML = `<li><button data-chapter="-1"><span>↖</span>Титульный экран</button></li>` + deck.sections.map((section, index) => `<li><button data-chapter="${index}"><span>${String(index + 1).padStart(2, '0')}</span>${escapeHTML(section.title)}</button>${screens(section).length ? `<div class="contents-screens">${screens(section).map((label, screenIndex) => `<button data-chapter="${index}" data-step="${screenIndex === 0 ? 0 : 2}"><span>${index + 1}.${screenIndex + 1}</span>${escapeHTML(label)}</button>`).join('')}</div>` : ''}</li>`).join('');
  $('#progress').innerHTML = deck.sections.map((section, index) => `<button data-chapter="${index}" aria-label="${escapeHTML(section.title)}" title="${escapeHTML(section.title)}">${index + 1}</button>`).join('');
  document.querySelectorAll('[data-chapter]').forEach(button => button.addEventListener('click', () => {
    $('#contents-dialog').close();
    go(Number(button.dataset.chapter), Number(button.dataset.step) || 0, true);
  }));
  drawSpeaker();
  preloadPosters();
  go(...fromHash());
  addEventListener('hashchange', () => { const [index, requested] = fromHash(); go(index, requested, true); });
  requestAnimationFrame(tick);
} catch (error) {
  $('#loading-error').hidden = false;
  $('#start').disabled = true;
  console.error('Could not load presentation', error);
}
