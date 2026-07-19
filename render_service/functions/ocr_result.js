/* OCR recognition result card.  Presentation only: all values arrive precomputed. */
(function () {
  "use strict";

  const WIDTH = 1200;
  const HEIGHT = 800;
  const HEADER_TOP = 56;
  const HEADER_HEIGHT = 226;
  const CONTENT_TOP = 318;
  const COLORS = {
    ink: "#242542",
    muted: "#7b7e98",
    header: "#e5e6ed",
    paper: "#f8f8fc",
    indigo: "#292b53",
    indigoDeep: "#202143",
    panel: "rgba(255, 255, 255, 0.075)",
    line: "rgba(255, 255, 255, 0.15)",
    white: "#fbfbff",
    pink: "#ff5797",
    cyan: "#5ce9dc",
    yellow: "#f6c94d",
  };

  const DIFFICULTY_COLORS = {
    EASY: "#67d9ae",
    NORMAL: "#65bde7",
    HARD: "#ff7970",
    EXPERT: "#ff4e8b",
    MASTER: "#aa74e8",
    APPEND: "#d78e4b",
  };

  const DIFFICULTY_TONES = {
    EASY: "#397d69",
    NORMAL: "#3c6f8c",
    HARD: "#8e4a48",
    EXPERT: "#9a3f64",
    MASTER: "#71529d",
    APPEND: "#8e6741",
  };

  const GRADE_COLORS = {
    "SSS+": ["#ef78e8", "#78bdf2"],
    SSS: ["#d18df0", "#8f62d7"],
    "SS+": ["#ae8deb", "#7866d4"],
    SS: ["#80a6ef", "#557cd3"],
    "S+": ["#6ed9dc", "#3c98c4"],
    S: ["#68d3a8", "#379b7d"],
    A: ["#b7d85c", "#769b39"],
    B: ["#f2c35b", "#c68932"],
    C: ["#f59960", "#cd624c"],
    D: ["#e983a8", "#ba4d74"],
  };

  const GRADE_DIAGONAL_POSITIONS = {
    three: [[42, 84], [80, 156], [118, 224]],
    two: [[52, 105], [108, 202]],
    one: [[79, 154]],
  };

  function textOr(value, fallback) {
    const text = String(value ?? "").trim();
    return text || fallback;
  }

  function numberOr(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function roundedRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  function fillRoundedRect(ctx, x, y, width, height, radius, fill) {
    roundedRect(ctx, x, y, width, height, radius);
    ctx.fillStyle = fill;
    ctx.fill();
  }

  function drawFittedText(ctx, text, x, y, maxWidth, startSize, minSize) {
    let size = startSize;
    while (size > minSize) {
      ctx.font = `700 ${size}px Arial, sans-serif`;
      if (ctx.measureText(text).width <= maxWidth) break;
      size -= 1;
    }
    ctx.font = `700 ${size}px Arial, sans-serif`;
    let displayed = text;
    if (ctx.measureText(displayed).width > maxWidth) {
      while (displayed.length > 1 && ctx.measureText(`${displayed}…`).width > maxWidth) {
        displayed = displayed.slice(0, -1);
      }
      displayed = `${displayed}…`;
    }
    ctx.fillText(displayed, x, y);
  }

  function loadDataImage(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("jacket image failed to load"));
      image.src = src;
    });
  }

  function drawJacketPlaceholder(ctx, x, y, size) {
    const gradient = ctx.createLinearGradient(x, y, x + size, y + size);
    gradient.addColorStop(0, "#575a83");
    gradient.addColorStop(1, "#2e3158");
    fillRoundedRect(ctx, x, y, size, size, 16, gradient);
    ctx.save();
    roundedRect(ctx, x, y, size, size, 16);
    ctx.clip();
    ctx.strokeStyle = "rgba(255,255,255,0.22)";
    ctx.lineWidth = 7;
    for (let offset = -size; offset < size * 2; offset += 38) {
      ctx.beginPath();
      ctx.moveTo(x + offset, y + size);
      ctx.lineTo(x + offset + size, y);
      ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = "rgba(255,255,255,0.88)";
    ctx.font = "700 20px Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("NO JACKET", x + size / 2, y + size / 2 + 7);
    ctx.textAlign = "left";
  }

  function drawJacket(ctx, image, x, y, size) {
    ctx.save();
    roundedRect(ctx, x, y, size, size, 16);
    ctx.clip();
    const scale = Math.max(size / image.width, size / image.height);
    const width = image.width * scale;
    const height = image.height * scale;
    ctx.drawImage(image, x + (size - width) / 2, y + (size - height) / 2, width, height);
    ctx.restore();
  }

  function difficultyFill(ctx, difficulty, x, y, width) {
    if (difficulty === "APPEND") {
      const gradient = ctx.createLinearGradient(x, y, x + width, y);
      gradient.addColorStop(0, "#f4ae59");
      gradient.addColorStop(0.55, "#d47bd9");
      gradient.addColorStop(1, "#6e9cf0");
      return gradient;
    }
    return DIFFICULTY_COLORS[difficulty] || COLORS.muted;
  }

  function drawBackgroundDecorations(ctx) {
    ctx.save();

    // A faint equalizer/display panel gives the lower area the visual rhythm
    // of the result screen while staying behind every readable value.
    ctx.fillStyle = "rgba(151, 160, 222, 0.055)";
    roundedRect(ctx, 526, 490, 345, 180, 22);
    ctx.fill();
    ctx.strokeStyle = "rgba(174, 185, 243, 0.09)";
    ctx.lineWidth = 2;
    ctx.stroke();

    const bars = [38, 76, 118, 54, 145, 102, 168, 82, 126, 46, 96, 134];
    bars.forEach((height, index) => {
      const x = 552 + index * 24;
      const y = 632 - height;
      fillRoundedRect(ctx, x, y, 13, height, 6, "rgba(170, 190, 249, 0.09)");
    });

    const triangles = [
      [575, 315, 46, -14, 18, 48], [1088, 299, 31, 13, -24, 38],
      [550, 728, 54, -10, 15, 38], [1130, 690, 42, 10, -28, 46],
      [626, 706, 28, 2, -9, 31], [1024, 734, 50, -7, 12, 33],
    ];
    triangles.forEach(([x, y, dx1, dy1, dx2, dy2], index) => {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + dx1, y + dy1);
      ctx.lineTo(x + dx2, y + dy2);
      ctx.closePath();
      ctx.fillStyle = index % 2 ? "rgba(255, 137, 188, 0.09)" : "rgba(99, 234, 222, 0.08)";
      ctx.fill();
    });
    ctx.restore();
  }

  function drawAttachedAchievementGrade(ctx, grade) {
    if (!grade) return;

    const x = 958;
    const y = HEADER_TOP;
    const width = 158;
    const height = HEADER_HEIGHT;
    const colors = GRADE_COLORS[grade] || ["#a8adc7", "#737994"];
    const gradeCharacters = grade.replace("+", "").split("");

    ctx.save();
    // This is an attached cutout in the song card, so its fill deliberately
    // matches the main result background instead of becoming a separate badge.
    ctx.fillStyle = COLORS.indigo;
    ctx.beginPath();
    ctx.moveTo(x + 7, y);
    ctx.lineTo(x + width, y);
    ctx.lineTo(x + width, y + height);
    ctx.lineTo(x, y + height);
    ctx.closePath();
    ctx.fill();

    const gradeGradient = ctx.createLinearGradient(x, y, x + width, y + height);
    gradeGradient.addColorStop(0, colors[0]);
    gradeGradient.addColorStop(1, colors[1]);
    ctx.fillStyle = gradeGradient;
    ctx.font = "800 92px Arial, sans-serif";
    ctx.textAlign = "center";
    const positions = gradeCharacters.length >= 3
      ? GRADE_DIAGONAL_POSITIONS.three
      : gradeCharacters.length === 2
        ? GRADE_DIAGONAL_POSITIONS.two
        : GRADE_DIAGONAL_POSITIONS.one;
    gradeCharacters.slice(0, positions.length).forEach((character, index) => {
      const [offsetX, offsetY] = positions[index];
      ctx.fillText(character, x + offsetX, y + offsetY);
    });
    if (grade.endsWith("+")) {
      ctx.font = "800 46px Arial, sans-serif";
      ctx.fillText("+", x + width - 24, y + 56);
    }
    ctx.textAlign = "left";
    ctx.restore();
  }

  function drawMetadata(ctx, data, x, y) {
    const difficulty = textOr(data.difficulty, "UNKNOWN").toUpperCase();
    const level = textOr(data.officialLevel, "?");
    const constant = textOr(data.communityConstant, "?");
    const status = textOr(data.status, "").toUpperCase();

    const difficultyWidth = Math.max(168, ctx.measureText(difficulty).width + 58);
    fillRoundedRect(ctx, x, y, difficultyWidth, 58, 13, difficultyFill(ctx, difficulty, x, y, difficultyWidth));
    ctx.fillStyle = COLORS.white;
    ctx.font = "700 27px Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(difficulty, x + difficultyWidth / 2, y + 38);

    let cursor = x + difficultyWidth + 16;
    const pills = [
      { label: `Lv.${level}`, fill: difficultyFill(ctx, difficulty, cursor, y, 100) },
      { label: `定数 ${constant}`, fill: DIFFICULTY_TONES[difficulty] || "#565978" },
    ];
    if (status === "AP" || status === "FC") {
      pills.push({
        label: status,
        fill: status === "AP" ? "#8e7137" : "#327e7a",
      });
    }
    for (const pill of pills) {
      const { label, fill } = pill;
      ctx.font = "700 23px Arial, sans-serif";
      const width = Math.max(96, ctx.measureText(label).width + 38);
      fillRoundedRect(ctx, cursor, y, width, 58, 13, fill);
      ctx.fillStyle = label === "AP" ? COLORS.yellow : COLORS.white;
      ctx.textAlign = "center";
      ctx.fillText(label, cursor + width / 2, y + 38);
      cursor += width + 12;
    }
    ctx.textAlign = "left";
  }

  function drawPaddedCount(ctx, value, x, y) {
    const count = Math.max(0, Math.trunc(numberOr(value)));
    const text = String(count).padStart(4, "0");
    const leadingZeroes = text.match(/^0+(?=\d)/)?.[0] || "";
    const significant = text.slice(leadingZeroes.length);
    ctx.font = "700 34px Arial, sans-serif";
    const totalWidth = ctx.measureText(text).width;
    const startX = x - totalWidth;
    ctx.fillStyle = "rgba(255,255,255,0.34)";
    ctx.fillText(leadingZeroes, startX, y);
    ctx.fillStyle = COLORS.white;
    ctx.fillText(significant, startX + ctx.measureText(leadingZeroes).width, y);
  }

  function drawJudgementRow(ctx, label, value, color, x, y, framed) {
    if (framed) {
      fillRoundedRect(ctx, x, y, 450, 56, 13, COLORS.panel);
    }
    if (label === "PERFECT") {
      const perfectGradient = ctx.createLinearGradient(x, y, x + 155, y + 40);
      perfectGradient.addColorStop(0, "#73f2e1");
      perfectGradient.addColorStop(0.48, "#81c9f3");
      perfectGradient.addColorStop(1, "#df87ee");
      ctx.fillStyle = perfectGradient;
    } else {
      ctx.fillStyle = color;
    }
    ctx.font = "700 28px Arial, sans-serif";
    ctx.fillText(label, x + 20, y + 38);
    drawPaddedCount(ctx, value, x + 424, y + 39);
  }

  window.registerRenderFunction("ocr_result", async function (data) {
    const canvas = document.getElementById("render-canvas");
    const ctx = canvas.getContext("2d");
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    ctx.textBaseline = "alphabetic";

    ctx.fillStyle = COLORS.indigo;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    const lowerGlow = ctx.createRadialGradient(940, 590, 10, 940, 590, 610);
    lowerGlow.addColorStop(0, "rgba(108, 88, 175, 0.3)");
    lowerGlow.addColorStop(1, "rgba(36, 37, 75, 0)");
    ctx.fillStyle = lowerGlow;
    ctx.fillRect(0, CONTENT_TOP - 22, WIDTH, HEIGHT - CONTENT_TOP + 22);
    drawBackgroundDecorations(ctx);

    fillRoundedRect(ctx, 34, HEADER_TOP, WIDTH - 68, HEADER_HEIGHT, 23, COLORS.header);
    ctx.fillStyle = "rgba(36, 37, 66, 0.08)";
    ctx.font = "800 188px Arial, sans-serif";
    ctx.fillText("RESULT", 50, 230);

    const jacketX = 86;
    const jacketY = 84;
    const jacketSize = 166;
    let jacket = null;
    const jacketSource = typeof data.jacket === "string" && data.jacket.startsWith("data:image/") ? data.jacket : "";
    if (jacketSource) {
      try { jacket = await loadDataImage(jacketSource); } catch (_) { jacket = null; }
    }
    if (jacket) drawJacket(ctx, jacket, jacketX, jacketY, jacketSize);
    else drawJacketPlaceholder(ctx, jacketX, jacketY, jacketSize);

    ctx.fillStyle = COLORS.ink;
    drawFittedText(ctx, textOr(data.title, "Unknown Song"), 282, 147, 830, 54, 28);
    drawMetadata(ctx, data, 282, 170);
    drawAttachedAchievementGrade(ctx, textOr(data.grade, "").toUpperCase());

    const judges = data.judges || {};
    const rows = [
      ["PERFECT", judges.perfect, COLORS.cyan, true],
      ["GREAT", judges.great, "#e890f1", false],
      ["GOOD", judges.good, "#75bdf3", true],
      ["BAD", judges.bad, "#f19a7b", false],
      ["MISS", judges.miss, "#d3d5e0", true],
    ];
    rows.forEach(([label, value, color, framed], index) => {
      drawJudgementRow(ctx, label, value, color, 86, CONTENT_TOP + index * 76, framed);
    });

    ctx.save();
    ctx.translate(680, CONTENT_TOP);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    roundedRect(ctx, 0, 0, 450, 360, 24);
    ctx.fill();
    ctx.strokeStyle = COLORS.line;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = COLORS.cyan;
    ctx.font = "800 26px Arial, sans-serif";
    ctx.letterSpacing = "5px";
    ctx.fillText("RATING", 724, CONTENT_TOP + 63);
    ctx.letterSpacing = "0px";
    ctx.fillStyle = COLORS.white;
    ctx.font = "800 76px Arial, sans-serif";
    ctx.fillText(numberOr(data.rating).toFixed(2), 720, CONTENT_TOP + 149);

    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(720, CONTENT_TOP + 186);
    ctx.lineTo(1084, CONTENT_TOP + 186);
    ctx.stroke();

    ctx.fillStyle = COLORS.pink;
    ctx.font = "800 26px Arial, sans-serif";
    ctx.letterSpacing = "5px";
    ctx.fillText("ACC", 724, CONTENT_TOP + 242);
    ctx.letterSpacing = "0px";
    ctx.fillStyle = COLORS.white;
    ctx.font = "800 69px Arial, sans-serif";
    ctx.fillText(`${numberOr(data.accuracy).toFixed(2)}%`, 720, CONTENT_TOP + 324);

    ctx.fillStyle = "rgba(255,255,255,0.64)";
    ctx.font = "600 19px Arial, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(`QQ ${textOr(data.qqNumber, "Unknown")}`, 1130, 754);
    ctx.textAlign = "left";
  });
})();
