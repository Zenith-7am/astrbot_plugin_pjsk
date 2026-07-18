// Difficulty ranking render function — dual mode (global + personal)
// Global: pure cover grid, 10/row, sorted by chart constant
// Personal: cover + score overlay, 7/row, only user's played charts
// All rating/level values are pre-computed by Python; JS only draws.
// Migrated from: emu-bot render_service/functions/difficulty.js

registerRenderFunction("difficulty", async function(data) {
  if (document.fonts) await document.fonts.ready;

  var canvas = document.getElementById("render-canvas");
  var ctx = canvas.getContext("2d");

  var isPersonal = data.mode === "personal";

  // --- Layout parameters ---
  var MARGIN_X = 40, MARGIN_Y = 30;
  var HEADER_H = 80, TIER_LABEL_H = 36, TIER_GAP = 16;
  var CARD_GAP = 4;
  var FOOTER_H = 40;

  var COLS, CARD_W, CARD_H, CANVAS_W;
  if (isPersonal) {
    COLS = 7;
    CARD_W = 140;
    CARD_H = 180;  // card + 40px text overlay at bottom
    CANVAS_W = MARGIN_X * 2 + COLS * CARD_W + (COLS - 1) * CARD_GAP;
  } else {
    COLS = 10;
    CARD_W = 108;
    CARD_H = 108;
    CANVAS_W = MARGIN_X * 2 + COLS * CARD_W + (COLS - 1) * CARD_GAP;
  }

  // --- Calculate total height ---
  var cardRowGap = 4;
  var totalH = HEADER_H + MARGIN_Y;
  for (var t = 0; t < data.tiers.length; t++) {
    var tierSongs = data.tiers[t].songs;
    if (!tierSongs || tierSongs.length === 0) continue;
    var numRows = Math.ceil(tierSongs.length / COLS);
    totalH += TIER_LABEL_H + numRows * CARD_H + (numRows - 1) * cardRowGap + TIER_GAP;
  }
  totalH += MARGIN_Y + FOOTER_H;

  canvas.width = CANVAS_W;
  canvas.height = totalH;

  // --- Helpers ---
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

  var CANVAS_COLORS = {
    gold: "#eab308", silver: "#9ca3af", bronze: "#cd7f32",
    blue: "#3b82f6", green: "#10b981", purple: "#8b5cf6",
    red: "#ef4444", orange: "#f97316", teal: "#14b8a6", pink: "#ec4899",
  };

  // --- Background ---
  var bgGrad = ctx.createLinearGradient(0, 0, CANVAS_W, 0);
  bgGrad.addColorStop(0, "#caf2f3");
  bgGrad.addColorStop(1, "#ecddec");
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, CANVAS_W, totalH);

  // --- Title ---
  ctx.fillStyle = "#1f2937";
  ctx.font = 'bold 32px "Outfit", "Noto Sans JP", sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(data.title, CANVAS_W / 2, HEADER_H / 2 + 10);

  // --- Subtitle line ---
  ctx.strokeStyle = "rgba(0,0,0,0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(MARGIN_X, HEADER_H);
  ctx.lineTo(CANVAS_W - MARGIN_X, HEADER_H);
  ctx.stroke();

  // --- Render tiers ---
  var currentY = HEADER_H + MARGIN_Y;

  for (var t = 0; t < data.tiers.length; t++) {
    var tier = data.tiers[t];
    var tierSongs = tier.songs;
    if (!tierSongs || tierSongs.length === 0) continue;

    // Tier label badge — constant value is pre-computed by Python
    var badgeW = 90, badgeH = 28, badgeX = MARGIN_X + 4, badgeY = currentY + 2;
    ctx.fillStyle = "rgba(6,182,212,0.15)";
    roundRect(ctx, badgeX, badgeY, badgeW, badgeH, 8);
    ctx.fill();
    ctx.strokeStyle = "rgba(6,182,212,0.35)";
    ctx.lineWidth = 1;
    roundRect(ctx, badgeX, badgeY, badgeW, badgeH, 8);
    ctx.stroke();
    ctx.fillStyle = "#0e7490";
    ctx.font = 'bold 18px "Outfit", sans-serif';
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
        ctx.fillText("▸ " + (tier.constant_label || tier.constant.toFixed(1)), badgeX + 10, badgeY + 4);

    // Load jackets for this tier
    var tierJackets = await Promise.all(tierSongs.map(async function(song) {
      try {
        var src = song.jacket;
        if (!src) return null;
        var img = new Image();
        img.src = src;
        await new Promise(function(resolve) { img.onload = resolve; img.onerror = resolve; });
        return img;
      } catch(e) { return null; }
    }));

    var tierContentY = currentY + TIER_LABEL_H;

    // Draw cards
    for (var i = 0; i < tierSongs.length; i++) {
      var song = tierSongs[i];
      var col = i % COLS;
      var row = Math.floor(i / COLS);
      var cx = MARGIN_X + col * (CARD_W + CARD_GAP);
      var cy = tierContentY + row * (CARD_H + cardRowGap);

      // Draw jacket — square in both modes
      var jacketH = isPersonal ? CARD_W : CARD_H;
      ctx.save();
      roundRect(ctx, cx, cy, CARD_W, jacketH, 8);
      ctx.clip();

      if (tierJackets[i]) {
        ctx.drawImage(tierJackets[i], cx, cy, CARD_W, jacketH);
      } else {
        // Fallback gray placeholder
        ctx.fillStyle = "#d1d5db";
        ctx.fillRect(cx, cy, CARD_W, jacketH);
      }
      ctx.restore();

      // Card border
      ctx.save();
      roundRect(ctx, cx, cy, CARD_W, jacketH, 8);
      ctx.strokeStyle = "rgba(0,0,0,0.08)";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();

      if (isPersonal) {
        // --- Personal mode: info card below square jacket ---
        var cardGap = 3;
        var cardY = cy + CARD_W + cardGap;
        var cardH = CARD_H - CARD_W - cardGap;  // 180 - 140 - 3 = 37

        // Card background — gradient echoing the page bg, translucent
        var cardGrad = ctx.createLinearGradient(cx, cardY, cx + CARD_W, cardY + cardH);
        cardGrad.addColorStop(0, "rgba(255,255,255,0.55)");
        cardGrad.addColorStop(1, "rgba(240,232,248,0.55)");
        ctx.fillStyle = cardGrad;
        roundRect(ctx, cx, cardY, CARD_W, cardH, 6);
        ctx.fill();

        // Subtle card border
        ctx.strokeStyle = "rgba(0,0,0,0.06)";
        ctx.lineWidth = 1;
        roundRect(ctx, cx, cardY, CARD_W, cardH, 6);
        ctx.stroke();

        // Status color — status is pre-computed by Python (1=FC, 2=AP, 0/other=CLEAR)
        var statusText, statusColor;
        if (song.status === 2) {
          statusText = "AP";
          statusColor = CANVAS_COLORS.gold;
        } else if (song.status === 1) {
          var residual = (song.judges && song.judges.great) ? song.judges.great : 0;
          statusText = residual > 0 ? "FC(-" + residual + ")" : "FC";
          statusColor = CANVAS_COLORS.green;
        } else {
          statusText = "CLEAR";
          statusColor = CANVAS_COLORS.silver;
        }

        // Accuracy — centered top (pre-computed by Python)
        ctx.fillStyle = "#1f2937";
        ctx.font = 'bold 14px "Outfit", sans-serif';
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(song.accuracy.toFixed(2) + "%", cx + CARD_W / 2, cardY + 13);

        // Power + status — centered bottom (power is pre-computed rating)
        ctx.fillStyle = statusColor;
        ctx.font = 'bold 12px "Outfit", sans-serif';
        ctx.fillText(song.power.toFixed(1) + "  " + statusText, cx + CARD_W / 2, cardY + 27);
      }
    }

    // Move to next tier
    var numRows = Math.ceil(tierSongs.length / COLS);
    currentY += TIER_LABEL_H + numRows * CARD_H + (numRows - 1) * cardRowGap + TIER_GAP;
  }

  // --- Footer ---
  ctx.fillStyle = "#9ca3af";
  ctx.font = '11px "Outfit", "Noto Sans JP", sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("Emu Bot · pjsk-rate.com", CANVAS_W / 2, totalH - FOOTER_H / 2);
});
