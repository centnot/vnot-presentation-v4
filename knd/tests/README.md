# Playback regression checks

Run with Node.js 20 or later, with no package installation:

```sh
node --test tests/playback-end.test.mjs
```

The test runs the actual `app.js` against the actual `content.json`. It locates
them beside `tests/`; in the original workspace it also supports
`handoff-package/tests/` beside `site/`.

The media model intentionally delays JPEG decoding and preserves the decoder's
last video frame. It catches the former end-of-video flash, unintended media
reloads/seeks, stale end events after navigation, and rejected old play attempts
after explicit replay. All real video sections in the deck are covered.

This is controller regression coverage, not a substitute for browser visual QA.

To verify that an earlier controller fails, set `KND_TEST_APP` to a separate copy
of its `app.js` before running the same command. The real site is never changed.
