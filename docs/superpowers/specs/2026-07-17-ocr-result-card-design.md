# OCR Result Card Design

## Goal

Add a local Canvas template named `ocr_result` so the PJSK render service can
preview an OCR result as an official-result-inspired image.  This slice is
strictly visual: it does not change OCR, score persistence, OneBot replies, or
the renderer port.

## Scope

The template is a 1200 x 800 PNG.  It uses an original composition inspired by
PJSK's result-screen hierarchy, without copying game UI assets or character
art:

1. A shallow light-grey header card contains, from left to right, a jacket,
   song title, and a single metadata line: difficulty, official level,
   community constant, and FC/AP status.
2. The lower dark-indigo area has a plain five-row judgement panel on the
   left: PERFECT, GREAT, GOOD, BAD, MISS.
3. The lower-right value stack is exactly `RATING`, its value, `ACC`, and its
   value.  It deliberately has no combo or additional score-status block.
4. The bottom-right corner displays `QQ <number>` so the image identifies the
   score owner.  The number is only rasterised into the returned image; the
   JS template must not log it or place it in file names.

## Input Contract

`window.__renderFunctions["ocr_result"](data)` accepts JSON with these fields:

```json
{
  "title": "ANiMA",
  "difficulty": "EXPERT",
  "officialLevel": 29,
  "communityConstant": "29.6+",
  "status": "FC",
  "jacket": null,
  "judges": {"perfect": 1057, "great": 2, "good": 0, "bad": 0, "miss": 0},
  "rating": 31.82,
  "accuracy": 99.91,
  "qqNumber": "10000001"
}
```

`jacket` is either `null` or an image data URL supplied by Python.  The
template must draw an in-card placeholder when it is absent or fails to load.
Missing text and numbers use display-safe fallbacks rather than throwing.  All
metrics are precomputed by Python; JavaScript performs no rating or accuracy
calculation.

## Rendering Rules

- Difficulty colours are data-independent presentation mapping only; APPEND
  may use a gradient, while other difficulties use fixed palette values.
- The title must fit its column through font shrinking then ellipsis.
- The header status displays only AP or FC; any other/missing value is hidden.
- The rendered canvas is opaque and has exact dimensions 1200 x 800.
- The template uses no network requests, external fonts, or external images.

## Integration and Failure Behaviour

`render_service/main.py` already discovers each function file and exposes it
at `/render/<file-stem>`.  Adding `render_service/functions/ocr_result.js`
therefore registers `/render/ocr_result` without server routing changes.

This task also adds a fictional fixture and lets `tools/render_preview.py
--template ocr_result` select it by default.  A real Playwright test validates
that the endpoint returns a non-empty PNG.  Runtime wiring from a successful
OCR reply to this template remains a later, separate change; a render failure
must eventually preserve the current text reply.
