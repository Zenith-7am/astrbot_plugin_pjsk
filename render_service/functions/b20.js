// B20 render function — Canvas rendering for B20 query results.
// All rating/level values are pre-computed by Python; JS only draws.
// Original: f8_function.js from pjsk-rate.vercel.app
// Migrated from: emu-bot render_service/functions/b20.js

registerRenderFunction("b20", async function(data) {
  // Wait for fonts
  if (document.fonts) await document.fonts.ready;

  var canvas = document.getElementById("render-canvas");
  var ctx = canvas.getContext("2d");
  var W = 1200, H = 1480;
  canvas.width = W;
  canvas.height = H;

  var e = data;
  var r = data.isAppendExcluded;
  var n = data.currentPercentile;
  var s = data.displayRank;

  // --- Helper: rounded rectangle ---
  var roundRect = function(c, x, y, w, h, rad) {
    c.beginPath();
    c.moveTo(x + rad, y);
    c.lineTo(x + w - rad, y);
    c.quadraticCurveTo(x + w, y, x + w, y + rad);
    c.lineTo(x + w, y + h - rad);
    c.quadraticCurveTo(x + w, y + h, x + w - rad, y + h);
    c.lineTo(x + rad, y + h);
    c.quadraticCurveTo(x, y + h, x, y + h - rad);
    c.lineTo(x, y + rad);
    c.quadraticCurveTo(x, y, x + rad, y);
    c.closePath();
  };

  // --- Helper: rainbow gradient ---
  var rainbowGradient = function(c, cx, width, mode) {
    var g = c.createLinearGradient(cx - width / 2, 0, cx + width / 2, 0);
    var lightColors = ["#ff7ab8", "#ffbf70", "#e0e048", "#59eb7e", "#5eb2ff", "#b170eb", "#ff7ab8"];
    var darkColors  = ["#ef4444", "#f97316", "#eab308", "#10b981", "#06b6d4", "#8b5cf6", "#ef4444"];
    var colors = mode === "dark" ? darkColors : lightColors;
    colors.forEach(function(color, i) { g.addColorStop(i / (colors.length - 1), color); });
    return g;
  };

  // --- CANVAS_COLORS defaults ---
  var CANVAS_COLORS = {
    gold: "#eab308",
    silver: "#9ca3af",
    bronze: "#cd7f32",
    blue: "#3b82f6",
    green: "#10b981",
    purple: "#8b5cf6",
    red: "#ef4444",
    orange: "#f97316",
    teal: "#14b8a6",
    pink: "#ec4899",
  };

  // --- Load jacket images from data URLs ---
  var jacketImages = await Promise.all(e.b20.map(async function(song) {
    try {
      var src = song.jacket; // data URL from bot prefetch
      if (!src) return null;
      var img = new Image();
      img.src = src;
      await new Promise(function(resolve) { img.onload = resolve; img.onerror = resolve; });
      return img;
    } catch { return null; }
  }));

  // --- Background gradient ---
  var bgGrad = ctx.createLinearGradient(0, 0, W, 0);
  bgGrad.addColorStop(0, "#caf2f3");
  bgGrad.addColorStop(1, "#ecddec");
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, W, H);

  // --- Header: title ---
  ctx.fillStyle = "#1f2937";
  ctx.font = '900 42px "Outfit", "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("プロセカレート", W / 2, 60);

  // --- Header: white card ---
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.1)";
  ctx.shadowBlur = 20;
  ctx.shadowOffsetY = 10;
  ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
  roundRect(ctx, 50, 140, 1100, 240, 24);
  ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,0.6)";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.restore();

  // --- APPEND excluded badge ---
  if (r) {
    ctx.save();
    ctx.font = 'bold 24px "Noto Sans SC", "Noto Sans CJK SC", "Noto Sans JP", sans-serif';
    var appendText = "不含APPEND";
    var appendW = ctx.measureText(appendText).width + 40;
    var appendH = 48;
    var appendX = 1150 - appendW - 30;
    var appendY = 116;
    ctx.shadowColor = "rgba(0,0,0,0.15)";
    ctx.shadowBlur = 8;
    ctx.shadowOffsetY = 4;
    ctx.fillStyle = "rgba(187,49,243,0.9)";
    roundRect(ctx, appendX, appendY, appendW, appendH, 24);
    ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.fillStyle = "#fff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(appendText, appendX + appendW / 2, appendY + appendH / 2 + 2);
    ctx.restore();
  }

  // --- Player Class icon ---
  var pcX = 220;
  ctx.font = "60px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  var pcIcon = e.playerClass.name === "SEKAI MASTER" ? "🌐" : e.playerClass.icon;
  ctx.fillText(pcIcon, pcX, 210);

  // --- Player Class name + stars ---
  var isSekaiMaster = e.playerClass.name === "SEKAI MASTER";
  var isGrandMaster = e.playerClass.name === "Grand Master";
  var stars = e.playerClass.stars;
  var pcColor = CANVAS_COLORS[e.playerClass.fallbackColor] || "#1f2937";
  var spColor = e.sp >= 3939 ? "#eab308" : CANVAS_COLORS[e.playerClass.fallbackColor] || "#1f2937";
  var useShadow = false, useGlow = false;
  var spX = 580;

  if (e.sp >= 3939 || isSekaiMaster) {
    pcColor = rainbowGradient(ctx, pcX, 260, "dark");
    spColor = rainbowGradient(ctx, spX, 280, "dark");
    useShadow = true; useGlow = true;
  } else if (isGrandMaster) {
    if (stars >= 5) {
      pcColor = rainbowGradient(ctx, pcX, 260, "dark");
      spColor = rainbowGradient(ctx, spX, 280, "dark");
      useShadow = true; useGlow = true;
    } else {
      pcColor = rainbowGradient(ctx, pcX, 260, "light");
      spColor = rainbowGradient(ctx, spX, 280, "light");
    }
  }

  ctx.font = '900 34px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillStyle = pcColor;
  if (useShadow) { ctx.shadowColor = "rgba(0,0,0,0.2)"; ctx.shadowBlur = 4; ctx.shadowOffsetY = 2; }
  ctx.fillText(e.playerClass.name, pcX, 275);
  ctx.shadowColor = "transparent";

  if (e.playerClass.name === "SEKAI MASTER") {
    ctx.fillStyle = "#eab308";
    ctx.font = "bold 24px sans-serif";
    ctx.fillText("⭐️10", pcX, 320);
  } else if (e.playerClass.name === "Grand Master") {
    ctx.fillStyle = "#eab308";
    ctx.font = "bold 24px sans-serif";
    ctx.fillText("⭐️" + e.playerClass.stars, pcX, 320);
  } else {
    var starX = pcX - 48 + 12;
    ctx.font = "24px sans-serif";
    for (var si = 0; si < 4; si++) {
      ctx.fillStyle = si < e.playerClass.stars ? "#eab308" : "#d1d5db";
      ctx.fillText("★", starX + si * 24, 320);
    }
  }

  // --- Percentile / rank badge ---
  if ((n !== undefined || s !== undefined) && !["Silver", "Bronze", "Beginner"].includes(e.playerClass.name)) {
    ctx.save();
    ctx.font = 'bold 18px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
    var rankText = s !== undefined ? s.toLocaleString() + " 位" : "上位 " + n.toFixed(1) + "%";
    var rankW = ctx.measureText(rankText).width + 16 * 2;
    var rankH = 34;
    var rankX = pcX - rankW / 2;
    var rankY = 345;
    var rankGrad = ctx.createLinearGradient(rankX, 0, rankX + rankW, 0);
    rankGrad.addColorStop(0, "#f0fdfa");
    rankGrad.addColorStop(1, "#ecfdf5");
    ctx.fillStyle = rankGrad;
    ctx.shadowColor = "rgba(0,0,0,0.05)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 2;
    roundRect(ctx, rankX, rankY, rankW, rankH, rankH / 2);
    ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.strokeStyle = "#99f6e4";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = "#0f766e";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(rankText, pcX, rankY + rankH / 2 + 1);
    ctx.restore();
  }

  // --- SEKAI POWER ---
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = 'bold 20px "Outfit", "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillStyle = "#6b7280";
  ctx.fillText("SEKAI POWER", spX, 200);

  var spStr = e.sp.toFixed(2);
  var spParts = spStr.split(".");
  var spInt = spParts[0];
  var spDec = spParts[1];
  var hasDecimal = spDec !== "00";
  var decStr = hasDecimal ? "." + spDec : "";

  ctx.font = '900 110px "Outfit", sans-serif';
  var intWidth = ctx.measureText(spInt).width;
  ctx.font = '900 55px "Outfit", sans-serif';
  var decWidth = hasDecimal ? ctx.measureText(decStr).width : 0;
  var totalWidth = intWidth + decWidth;
  var spStartX = spX - totalWidth / 2;

  ctx.fillStyle = spColor;
  if (useGlow) { ctx.shadowColor = "rgba(0,0,0,0.2)"; ctx.shadowBlur = 8; ctx.shadowOffsetY = 4; }
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  var spBaseline = 345;

  ctx.font = '900 110px "Outfit", sans-serif';
  ctx.fillText(spInt, spStartX, spBaseline);
  if (hasDecimal) {
    ctx.font = '900 55px "Outfit", sans-serif';
    ctx.fillText(decStr, spStartX + intWidth, spBaseline);
  }
  ctx.shadowColor = "transparent";

  // --- Divider line ---
  ctx.strokeStyle = "#e5e7eb";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(860, 160);
  ctx.lineTo(860, 360);
  ctx.stroke();

  // --- Right column stats ---
  var statLeft = 890, statRight = 1110;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";

  // B20 average
  ctx.fillStyle = "#6b7280";
  ctx.font = 'bold 18px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillText("べ枠平均", statLeft, 195);
  ctx.textAlign = "right";
  ctx.font = 'bold 34px "Outfit", sans-serif';
  ctx.fillStyle = "#1f2937";
  ctx.fillText(Number(e.b20Avg).toFixed(2).replace(/\.00$/, ""), statRight, 195);

  // FC bonus
  ctx.textAlign = "left";
  ctx.fillStyle = "#6b7280";
  ctx.font = 'bold 18px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillText("全FCボーナス", statLeft, 260);
  ctx.textAlign = "right";
  ctx.font = 'bold 34px "Outfit", sans-serif';
  ctx.fillStyle = "#4ade80";
  ctx.fillText("+" + Number(e.fcBonus).toFixed(1).replace(/\.00$/, ""), statRight, 260);

  // AP bonus
  ctx.textAlign = "left";
  ctx.fillStyle = "#6b7280";
  ctx.font = 'bold 18px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillText("全APボーナス", statLeft, 325);
  var apGrad = ctx.createLinearGradient(statRight - 120, 0, statRight, 0);
  apGrad.addColorStop(0, "#9d94fe");
  apGrad.addColorStop(1, "#fe80c0");
  ctx.textAlign = "right";
  ctx.font = 'bold 34px "Outfit", sans-serif';
  ctx.fillStyle = apGrad;
  ctx.fillText("+" + Number(e.masterBonus).toFixed(1).replace(/\.00$/, ""), statRight, 325);

  // --- B20 card area ---
  ctx.textBaseline = "top";
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.1)";
  ctx.shadowBlur = 20;
  ctx.shadowOffsetY = 10;
  ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
  roundRect(ctx, 50, 400, 1100, 1010, 24);
  ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,0.6)";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.restore();

  ctx.fillStyle = "#1f2937";
  ctx.font = 'bold 26px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.textAlign = "left";
  ctx.fillText("ベスト枠（上位20曲）", 90, 450);

  // --- B20 song cards (5 columns x 4 rows) ---
  var COLS = 5;
  var cardW = 188, cardH = 188;
  var cardStartX = 90;
  var cardGap = (1020 - cardW * COLS) / (COLS - 1);
  var cardRowGap = 24;
  var cardStartY = 490;

  for (var idx = 0; idx < e.b20.length; idx++) {
    var song = e.b20[idx];
    var col = idx % COLS;
    var row = Math.floor(idx / COLS);
    var cx = cardStartX + col * (cardW + cardGap);
    var cy = cardStartY + row * (cardH + cardRowGap);

    // Jacket image or gray placeholder
    ctx.save();
    roundRect(ctx, cx, cy, cardW, cardH, 16);
    ctx.clip();
    if (jacketImages[idx]) {
      ctx.drawImage(jacketImages[idx], cx, cy, cardW, cardH);
    } else {
      ctx.fillStyle = "#d1d5db";
      ctx.fillRect(cx, cy, cardW, cardH);
    }

    // Dark gradient overlay
    var overlayGrad = ctx.createLinearGradient(0, cy, 0, cy + cardH);
    overlayGrad.addColorStop(0, "rgba(0,0,0,0)");
    overlayGrad.addColorStop(0.4, "rgba(0,0,0,0.1)");
    overlayGrad.addColorStop(1, "rgba(0,0,0,0.85)");
    ctx.fillStyle = overlayGrad;
    ctx.fillRect(cx, cy, cardW, cardH);
    ctx.restore();

    // Rank badge (#1, #2, #3, ...)
    ctx.save();
    var rankNum = idx + 1;
    ctx.font = 'bold 18px "Outfit", sans-serif';
    var rankLabel = "#" + rankNum;
    var rankLabelW = ctx.measureText(rankLabel).width + 16;
    var rankLabelH = 26;
    var badgeBg, badgeFg;
    if (rankNum === 1) { badgeBg = "#facc15"; badgeFg = "#000000"; }
    else if (rankNum === 2) { badgeBg = "#e5e7eb"; badgeFg = "#000000"; }
    else if (rankNum === 3) { badgeBg = "#cd7f32"; badgeFg = "#ffffff"; }
    else { badgeBg = "rgba(0, 0, 0, 0.8)"; badgeFg = "#facc15"; }

    ctx.fillStyle = badgeBg;
    roundRect(ctx, cx + 8, cy + 8, rankLabelW, rankLabelH, 6);
    ctx.fill();
    ctx.fillStyle = badgeFg;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(rankLabel, cx + 8 + rankLabelW / 2, cy + 8 + rankLabelH / 2 + 1.5);
    ctx.restore();

    // --- Achievement rate + rank badge ---
    var achRate = song.achievementRate != null ? song.achievementRate : (song.status === 2 ? 101 : null);
    if (achRate != null) {
      ctx.save();
      var achText = achRate.toFixed(4) + "%";
      var rankName = "-";
      var rankColor = "#fff";
      var isRainbowRank = false;

      if (achRate >= 101) { rankName = "SSS+"; isRainbowRank = true; }
      else if (achRate >= 100.9) { rankName = "SSS+"; rankColor = "#fcd34d"; }
      else if (achRate >= 100.75) { rankName = "SSS"; rankColor = "#f59e0b"; }
      else if (achRate >= 100) { rankName = achRate >= 100.5 ? "SS+" : "SS"; rankColor = "#facc15"; }
      else if (achRate >= 99) { rankName = achRate >= 99.5 ? "S+" : "S"; rankColor = "#fb923c"; }
      else if (achRate >= 98) { rankName = achRate >= 98.5 ? "A+" : "A"; rankColor = "#ef4444"; }
      else if (achRate >= 95) { rankName = "B"; rankColor = "#3b82f6"; }
      else if (achRate >= 90) { rankName = "C"; rankColor = "#10b981"; }
      else { rankName = "D"; rankColor = "#a855f7"; }

      var achBarColor = "#9ca3af";
      var useAchGradient = false;
      if (achRate >= 101) useAchGradient = true;
      else if (achRate >= 100.9) achBarColor = "#df57f4ff";
      else if (achRate >= 100.75) achBarColor = "#b270f0ff";
      else if (achRate >= 100.5) achBarColor = "#9a69eeff";
      else if (achRate >= 100) achBarColor = "#4c80f0ff";
      else if (achRate >= 99.5) achBarColor = "#32b0d0ff";
      else if (achRate >= 99) achBarColor = "#1fb384ff";
      else if (achRate >= 98) achBarColor = "#7ebc26ff";
      else if (achRate >= 95) achBarColor = "#e4a827ff";
      else if (achRate >= 90) achBarColor = "#fa8029ff";
      else achBarColor = "#f43f5e";

      ctx.font = '900 17px "Outfit", sans-serif';
      var achW = ctx.measureText(achText).width;
      ctx.font = 'italic 900 18px "Arial Black", "Outfit", sans-serif';
      var rankW2 = ctx.measureText(rankName).width;

      var achBoxW = achW + 15;
      var rankBoxW = rankW2 + 15;
      var achBoxH = 22;
      var rankBoxH = rankName !== "-" ? 18 : 0;
      var achRight = cx + cardW - 8;
      var achX = achRight - achBoxW;
      var rankX = achRight - rankBoxW;
      var achY = cy + 8;

      ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
      roundRect(ctx, achX, achY, achBoxW, achBoxH, 4);
      ctx.fill();
      if (rankBoxH > 0) {
        roundRect(ctx, rankX, achY + achBoxH, rankBoxW, rankBoxH, 4);
        ctx.fill();
        ctx.fillRect(achRight - 4, achY + achBoxH - 4, 4, 8);
        ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        var lineLeft = Math.min(achX, rankX);
        ctx.moveTo(lineLeft, achY + achBoxH);
        ctx.lineTo(achRight, achY + achBoxH);
        ctx.stroke();
      }

      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = '900 17px "Outfit", sans-serif';
      var achCenterX = achX + achBoxW / 2;
      if (useAchGradient) {
        ctx.fillStyle = rainbowGradient(ctx, achCenterX, achBoxW);
        ctx.shadowColor = "rgba(0,0,0,0.5)";
        ctx.shadowBlur = 4;
      } else {
        ctx.fillStyle = achBarColor;
        ctx.shadowColor = "transparent";
      }
      ctx.fillText(achText, achCenterX, achY + achBoxH / 2 + 1);

      if (rankBoxH > 0) {
        ctx.font = 'italic 900 18px "Arial Black", "Outfit", sans-serif';
        var rankCenterX = rankX + rankBoxW / 2;
        if (isRainbowRank) {
          ctx.fillStyle = rainbowGradient(ctx, rankCenterX, rankBoxW);
          ctx.shadowColor = "rgba(0,0,0,0.5)";
          ctx.shadowBlur = 4;
        } else {
          ctx.fillStyle = rankColor;
          ctx.shadowColor = "transparent";
        }
        ctx.fillText(rankName, rankCenterX, achY + achBoxH + rankBoxH / 2 + 1);
      }
      ctx.restore();
    }

    // --- Difficulty badge ---
    ctx.save();
    var diffLabelMap = { master: "MAS", append: "APD", expert: "EXP", hard: "HD", normal: "NM", easy: "EZ" };
    var diffLabel = diffLabelMap[song.difficulty] || "EXP";
    var levelLabel = song.displayLevel || song.level.toString();
    ctx.font = 'bold 11px "Outfit", sans-serif';
    var diffW = ctx.measureText(diffLabel).width;
    ctx.font = 'bold 16px "Outfit", sans-serif';
    var lvW = ctx.measureText(levelLabel).width;
    var gap = 4, pad = 8;
    var badgeW = diffW + gap + lvW + pad * 2;
    var badgeH = 22;
    var badgeX = cx + 8;
    var badgeY = cy + cardH - 72;

    if (song.difficulty === "append") {
      var diffGrad = ctx.createLinearGradient(badgeX, 0, badgeX + badgeW, 0);
      diffGrad.addColorStop(0, "rgba(157,148,254,0.9)");
      diffGrad.addColorStop(1, "rgba(254,128,192,0.9)");
      ctx.fillStyle = diffGrad;
    } else {
      var diffColorMap = {
        master: "rgba(187,49,243,0.9)",
        expert: "rgba(238,69,101,0.9)",
        hard: "rgba(240,227,17,0.92)",
        normal: "rgba(59,130,246,0.9)",
        easy: "rgba(16,185,129,0.9)"
      };
      ctx.fillStyle = diffColorMap[song.difficulty] || "rgba(238,69,101,0.9)";
    }
    roundRect(ctx, badgeX, badgeY, badgeW, badgeH, 4);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    var badgeTextY = badgeY + badgeH - 5;
    ctx.font = 'bold 11px "Outfit", sans-serif';
    ctx.fillText(diffLabel, badgeX + pad, badgeTextY - 1);
    ctx.font = 'bold 16px "Outfit", sans-serif';
    ctx.fillText(levelLabel, badgeX + pad + diffW + gap, badgeTextY);
    ctx.restore();

    // --- Song title ---
    ctx.save();
    ctx.font = 'bold 15px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
    ctx.fillStyle = "#fff";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    var title = song.title;
    if (ctx.measureText(title).width > cardW - 20) {
      while (title.length > 0 && ctx.measureText(title + "...").width > cardW - 20) {
        title = title.slice(0, -1);
      }
      title += "...";
    }
    ctx.shadowColor = "rgba(0,0,0,0.8)";
    ctx.shadowBlur = 4;
    ctx.fillText(title, cx + 10, cy + cardH - 26);
    ctx.restore();

    // --- FC/AP label + power ---
    ctx.save();
    ctx.font = 'bold 18px "Outfit", sans-serif';
    ctx.fillStyle = song.status === 2 ? "#facc15" : "#4ade80";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.shadowColor = "rgba(0,0,0,0.8)";
    ctx.shadowBlur = 4;
    var fcLabel = song.status === 2 ? "AP" : "FC";
    ctx.fillText(fcLabel, cx + 10, cy + cardH - 6);

    // FC residual count (non-PERFECT count: great+good+bad+miss)
    if (song.status === 1 && song.judges) {
      var residual = (song.judges.great || 0) + (song.judges.good || 0) + (song.judges.bad || 0) + (song.judges.miss || 0);
      var residualText = "(-" + residual + ")";
      var fcW = ctx.measureText(fcLabel).width;
      var resX = cx + 10 + fcW + 6;
      ctx.shadowColor = "transparent";
      ctx.font = 'bold 12px "Outfit", sans-serif';
      var resW = ctx.measureText(residualText).width + 8;
      var resH = 17;
      var resY = cy + cardH - 7 - 16;
      ctx.fillStyle = "rgba(0, 0, 0, 0.3)";
      roundRect(ctx, resX, resY, resW, resH, 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(residualText, resX + resW / 2, resY + resH / 2 + 1);
    }

    // Power value — pre-computed by Python (rating)
    ctx.font = 'bold 18px "Outfit", sans-serif';
    ctx.shadowColor = "rgba(0,0,0,0.8)";
    ctx.shadowBlur = 4;
    ctx.textBaseline = "bottom";
    ctx.fillStyle = "#fff";
    ctx.textAlign = "right";
    ctx.fillText(Number(song.power).toFixed(1).replace(/\.0$/, ""), cx + cardW - 10, cy + cardH - 6);
    ctx.restore();
  }

  // --- Footer ---
  ctx.save();
  ctx.fillStyle = "#6b7280";
  ctx.font = 'bold 20px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.fillText("譜面定数参照元: スプシ用難易度表PENTATONIC v30 (製作者: 腐食 / 부식 様)", 1110, 1370);
  ctx.restore();

  ctx.textAlign = "right";
  ctx.textBaseline = "bottom";
  ctx.fillStyle = "#6b7280";
  ctx.font = 'bold 18px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillText("Generated by プロセカレート", W - 20, H - 28);
  ctx.font = 'bold 16px "Outfit", sans-serif';
  ctx.fillText("https://pjsk-rate.vercel.app", W - 20, H - 8);

  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillStyle = "#6b7280";
  ctx.font = '14px "Noto Sans JP", "Noto Sans CJK JP", sans-serif';
  ctx.fillText("※本画像におけるロゴ・背景・楽曲ジャケット画像の著作権は、全て著作権所有者に帰属します。", 20, H - 28);
  ctx.fillText("※本画像は非公式のものであり、株式会社Colorful Palette様及びその関連会社とは一切関係ありません。", 20, H - 8);

  // No toDataURL — render service screenshots the canvas directly
});
