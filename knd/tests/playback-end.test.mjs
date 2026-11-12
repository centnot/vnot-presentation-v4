import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = [resolve(here, '..'), resolve(here, '../../site')]
  .find(path => existsSync(join(path, 'app.js')) && existsSync(join(path, 'content.json')));
assert.ok(siteRoot, 'Place tests/ next to app.js and content.json, or keep handoff-package/ beside site/');
const appPath = process.env.KND_TEST_APP ? resolve(process.env.KND_TEST_APP) : join(siteRoot, 'app.js');
const appSource = readFileSync(appPath, 'utf8');
const content = JSON.parse(readFileSync(join(siteRoot, 'content.json'), 'utf8'));
const videoSections = content.sections.filter(section => section.video);

/**
 * Browser protocol model for the production app, not a copy of its controller.
 * Images decode separately from src assignment. Video keeps its decoded final
 * frame when paused, but play() on an ended resource rewinds it like a browser.
 * Presentation-affecting writes are observed so a first-JPEG flash is visible
 * even when the controller immediately requests the correct final JPEG.
 */
async function openSection(id, { deferredPlay = false } = {}) {
  const writes = [];
  const elements = new Map();
  const globalHandlers = new Map();
  const documentHandlers = new Map();
  const pendingPlays = [];
  const errors = [];
  let now = 1000;
  let timerId = 0;

  class Element {
    constructor(name) {
      this.id = name;
      this.handlers = new Map();
      this.attributes = new Map();
      this.dataset = {};
      this.style = {};
      this._hidden = false;
      this._src = '';
      this.displayedImage = '';
      this.pendingImage = '';
      this.innerHTML = '';
      this.textContent = '';
      this.open = false;
      this.classes = new Set();
      this.classList = {
        contains: name => this.classes.has(name),
        add: name => this.setClass(name, true),
        remove: name => this.setClass(name, false),
        toggle: (name, value) => {
          const wanted = value === undefined ? !this.classes.has(name) : Boolean(value);
          this.setClass(name, wanted);
          return wanted;
        },
      };
    }
    setClass(name, value) {
      if (value) this.classes.add(name); else this.classes.delete(name);
      if (this.id === 'video') writes.push({ property: 'video.class', name, value });
    }
    get hidden() { return this._hidden; }
    set hidden(value) {
      this._hidden = Boolean(value);
      if (['video', 'still'].includes(this.id)) writes.push({ property: `${this.id}.hidden`, value });
    }
    get src() { return this._src; }
    set src(value) {
      this._src = value;
      if (this.id === 'still') {
        writes.push({ property: 'still.src', value });
        // Keep the previous displayed JPEG until the network/decode finishes.
        this.pendingImage = value;
      }
    }
    addEventListener(type, handler) {
      const handlers = this.handlers.get(type) ?? [];
      handlers.push(handler);
      this.handlers.set(type, handlers);
    }
    emit(type, extra = {}) {
      const event = { target: this, detail: 1, preventDefault() {}, ...extra };
      for (const handler of this.handlers.get(type) ?? []) handler(event);
    }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    querySelectorAll() { return []; }
    querySelector(selector) { return get(`${this.id}:${selector}`); }
    closest(selector) {
      if (selector === 'button,a' && ['next', 'previous', 'pause'].includes(this.id)) return this;
      return null;
    }
    showModal() { this.open = true; }
    close() { this.open = false; this.emit('close'); }
  }

  class Media extends Element {
    constructor() {
      super('video');
      this._time = 0;
      this._poster = '';
      this.duration = 13;
      this.ended = false;
      this.paused = true;
      this.readyState = 4;
      this.decoderFrame = 'empty';
      this.playCount = 0;
      this.loadCount = 0;
    }
    get src() { return this._src; }
    set src(value) {
      this._src = value;
      this.ended = false;
      this.decoderFrame = `first:${value}`;
      writes.push({ property: 'video.src', value });
    }
    get poster() { return this._poster; }
    set poster(value) { this._poster = value; writes.push({ property: 'video.poster', value }); }
    get currentTime() { return this._time; }
    set currentTime(value) {
      this._time = value;
      this.ended = false;
      this.decoderFrame = value === 0 ? `first:${this.src}` : `seek:${value}:${this.src}`;
      writes.push({ property: 'video.currentTime', value });
    }
    load() {
      this.loadCount += 1;
      this._time = 0;
      this.ended = false;
      this.decoderFrame = `first:${this.src}`;
      writes.push({ property: 'video.load' });
    }
    pause() { this.paused = true; }
    play() {
      this.playCount += 1;
      if (this.ended) {
        this._time = 0;
        this.ended = false;
        this.decoderFrame = `first:${this.src}`;
        writes.push({ property: 'video.automaticRewind' });
      }
      this.paused = false;
      if (!deferredPlay) return Promise.resolve();
      return new Promise((resolve, reject) => pendingPlays.push({ resolve, reject }));
    }
    reachEnd() {
      // These changes belong to normal decoding, not application assignments.
      this._time = this.duration;
      this.ended = true;
      this.paused = true;
      this.decoderFrame = `final:${this.src}`;
    }
  }

  function get(name) {
    if (!elements.has(name)) elements.set(name, name === 'video' ? new Media() : new Element(name));
    return elements.get(name);
  }
  const video = get('video');
  const still = get('still');
  const location = { pathname: '/knd/', search: '', hash: `#${id}` };
  const document = {
    hidden: false,
    fullscreenElement: null,
    documentElement: { requestFullscreen: () => Promise.resolve() },
    body: get('body'),
    querySelector(selector) {
      if (selector === 'dialog[open]') return [get('contents-dialog'), get('notes-dialog')].find(el => el.open) ?? null;
      if (selector.startsWith('#show-')) return null;
      return get(selector.slice(1));
    },
    querySelectorAll(selector) {
      if (selector === 'dialog') return [get('contents-dialog'), get('notes-dialog')];
      return [];
    },
    addEventListener(type, handler) { documentHandlers.set(type, handler); },
  };
  const context = {
    document, location,
    innerWidth: 1920, innerHeight: 1080,
    performance: { now: () => now },
    console: { error: (...args) => errors.push(args) },
    history: { replaceState(_state, _unused, url) { location.hash = url.includes('#') ? url.slice(url.indexOf('#')) : ''; } },
    fetch: async () => ({ ok: true, json: async () => structuredClone(content) }),
    requestAnimationFrame: () => 1,
    setTimeout: () => ++timerId,
    clearTimeout() {},
    getSelection: () => null,
    addEventListener(type, handler) { globalHandlers.set(type, handler); },
  };
  // The actual buildless app uses top-level await but no module imports.
  await new vm.Script(`(async () => {\n${appSource}\n})()`, { filename: appPath })
    .runInNewContext(context, { timeout: 2000 });
  assert.deepEqual(errors, [], 'The production app should initialize successfully');
  assert.equal(video.dataset.section, id, 'The requested real section should be loaded');
  still.displayedImage = still.pendingImage;
  still.pendingImage = '';
  writes.length = 0;

  return {
    video, still, writes, pendingPlays, document,
    get,
    visibleFrame() {
      return video.hidden || video.classList.contains('stopped') ? `image:${still.displayedImage}` : video.decoderFrame;
    },
    finish() { video.reachEnd(); video.emit('ended'); },
    click(name) { now += 300; get(name).emit('click'); },
    key(code) {
      now += 300;
      globalHandlers.get('keydown')({ code, key: code === 'KeyR' ? 'r' : '', target: get('stage'), preventDefault() {} });
    },
    visibility(hidden) { document.hidden = hidden; documentHandlers.get('visibilitychange')(); },
  };
}

test(`natural completion holds the decoded final frame in all ${videoSections.length} real video sections`, async t => {
  assert.ok(videoSections.length > 0, 'The real deck must contain video sections');
  for (const section of videoSections) {
    await t.test(section.id, async () => {
      const page = await openSection(section.id);
      const source = page.video.src;
      const poster = page.video.poster;
      const loads = page.video.loadCount;
      page.finish();
      assert.equal(page.visibleFrame(), `final:${source}`, 'A cold final JPEG must never reveal the first-frame fallback');
      assert.equal(page.video.currentTime, page.video.duration, 'The playback position must remain at the end');
      assert.equal(page.video.src, source);
      assert.equal(page.video.poster, poster);
      assert.equal(page.video.loadCount, loads);
      assert.equal(page.video.hidden, false);
      assert.equal(page.video.classList.contains('stopped'), false);
      assert.deepEqual(page.writes, [], 'Completion must not assign media sources, seek, or change visible layers');
      page.visibility(true);
      page.visibility(false);
      assert.equal(page.visibleFrame(), `final:${source}`, 'Returning to the tab must keep the final frame');
      assert.equal(page.video.currentTime, page.video.duration);
    });
  }
});

test('a pending play rejection after completion does not enter the user-paused state', async () => {
  const page = await openSection(videoSections[0].id, { deferredPlay: true });
  assert.equal(page.pendingPlays.length, 1);
  page.finish();
  page.pendingPlays[0].reject(new Error('The media operation was superseded'));
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(page.get('pause').getAttribute('aria-label'), 'Приостановить');
  assert.equal(page.video.currentTime, page.video.duration);
  assert.equal(page.visibleFrame(), `final:${page.video.src}`);
});

test('a late ended event from the previous resource does not stop the next section', async () => {
  const firstIndex = content.sections.findIndex(section => section.video && !section.extra && !section.autoLandingSeconds);
  const section = content.sections[firstIndex];
  const next = content.sections[firstIndex + 1];
  assert.ok(next?.video, 'This fixture needs adjacent real video sections');
  const page = await openSection(section.id);
  page.click('next');
  assert.equal(page.video.dataset.section, next.id);
  assert.equal(page.video.ended, false);
  const source = page.video.src;
  const plays = page.video.playCount;
  page.writes.length = 0;
  // The queued event survives navigation; the new resource itself has not ended.
  page.video.emit('ended');
  assert.equal(page.video.paused, false, 'The next section must continue playing');
  assert.equal(page.video.src, source);
  assert.equal(page.video.playCount, plays);
  assert.equal(page.video.classList.contains('stopped'), false);
  assert.deepEqual(page.writes, []);
});

test('explicit replay starts at zero and an older play rejection cannot pause that replay', async () => {
  const page = await openSection(videoSections[0].id, { deferredPlay: true });
  const source = page.video.src;
  page.finish();
  const plays = page.video.playCount;
  page.key('KeyR');
  assert.equal(page.video.currentTime, 0);
  assert.equal(page.video.ended, false);
  assert.equal(page.video.paused, false);
  assert.equal(page.video.src, source);
  assert.equal(page.video.playCount, plays + 1);
  assert.equal(page.visibleFrame(), `first:${source}`);
  page.pendingPlays[0].reject(new Error('Old playback attempt rejected after replay'));
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(page.get('pause').getAttribute('aria-label'), 'Приостановить');
  assert.equal(page.video.paused, false);
  page.writes.length = 0;
  page.finish();
  assert.equal(page.visibleFrame(), `final:${source}`);
  assert.deepEqual(page.writes, []);
});
