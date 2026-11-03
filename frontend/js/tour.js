(function () {
  "use strict";

  var MENUS = {
    login: [
      {
        target: "#loginForm",
        title: "Masuk ke ENKRIPSIH",
        desc: "Pilih jenis akun dan masukkan password. Akun receiver wajib ganti password saat login pertama.",
      },
    ],
    commander: [
      {
        target: "#intelMessage",
        title: "Tulis pesan",
        desc: "Isi pesan yang akan dienkripsi di browser. Tidak ada plaintext yang meninggalkan perangkatmu.",
      },
      {
        target: "#recipientId",
        title: "Pilih anggota penerima",
        desc: "Pilih anggota tujuan. Kunci agen terisi otomatis jika tersedia di server.",
      },
      {
        target: "#btnTransmitIntel",
        title: "Enkripsi dan kirim",
        desc: "Tombol ini mengenkripsi pesan di perangkat lalu menyimpan ciphertext.",
      },
      {
        target: "#btnRefreshCommanderMsgs",
        title: "Lihat status pengiriman",
        desc: "Ciphertext yang sudah dikirim ditampilkan di sini, lengkap dengan status.",
      },
    ],
    members: [
      {
        target: "#recipientRegisterForm",
        title: "Daftarkan anggota baru",
        desc: "Isi nama dan secret key. Username dan password sementara muncul sekali, simpan dengan aman.",
      },
      {
        target: "#btnRefreshRecipients",
        title: "Daftar anggota",
        desc: "Anggota yang sudah terdaftar tampil di sini. Kunci lama tidak bisa dipulihkan dari server.",
      },
    ],
    receiver: [
      {
        target: "#receiverMessageList",
        title: "Kotak masuk",
        desc: "Pilih pesan di daftar kiri untuk membuka detailnya di panel kanan.",
      },
      {
        target: "#receiverMessageContainer",
        title: "Detail pesan",
        desc: "Setelah memilih pesan, area ini menampilkan isi pesan, challenge passkey, dan input respons.",
      },
      {
        target: "#btnRefreshReceiverMsgs",
        title: "Refresh pesan",
        desc: "Tekan ini untuk menarik pesan terbaru dari server.",
      },
    ],
  };

  var MENU_KEYS = {
    login: "enkripsih_tour_done_login_v2",
    commander: "enkripsih_tour_done_commander_v2",
    members: "enkripsih_tour_done_members_v2",
    receiver: "enkripsih_tour_done_receiver_v2",
  };

  var overlay, panelT, panelB, panelL, panelR, highlight, arrow, shaftW, shaft, card, titleEl, descEl,
      indicator, prevBtn, nextBtn, skipBtn;
  var index = 0;
  var total = 0;
  var activeMenu = null;
  var bodyLock = false;
  var mobileLock = false;
  var savedHtmlOverflow = "";
  var savedBodyOverflow = "";
  var overlayMounted = false;
  var rafScheduled = false;
  var lastStepKey = "";
  var savedScrollX = 0;
  var savedScrollY = 0;
  var savedBodyTop = "";
  var savedBodyLeft = "";
  var savedBodyWidth = "";

  function scheduleRender() {
    if (rafScheduled) return;
    rafScheduled = true;
    requestAnimationFrame(function () {
      rafScheduled = false;
      if (overlay && !overlay.hidden) render();
    });
  }

  function isElementVisible(elm) {
    if (!elm) return false;
    return !isHidden(elm) && elm.offsetWidth > 0;
  }

  function lockElement(elm, on) {
    if (!elm) return;
    if (on) {
      if (!elm.dataset.tourPrevOverflow) {
        elm.dataset.tourPrevOverflow = elm.style.overflow || "";
      }
      elm.dataset.tourLocked = "1";
      elm.style.overflow = "hidden";
    } else {
      if (elm.dataset.tourPrevOverflow) {
        elm.style.overflow = elm.dataset.tourPrevOverflow;
        delete elm.dataset.tourPrevOverflow;
      }
      delete elm.dataset.tourLocked;
    }
  }

  function isMobileViewport() {
    return window.matchMedia && window.matchMedia("(max-width: 480px)").matches;
  }

  function lockPage(on) {
    var body = document.body;
    if (isMobileViewport()) {
      // On a narrow screen, blocking the body with position:fixed would kill
      // programmatic scrolling to the tour target. Instead we only hide the
      // overflow so the user cannot scroll manually; the scroll position is
      // still settable, which is what scrollTargetIntoView relies on.
      if (on) {
        mobileLock = true;
        savedHtmlOverflow = document.documentElement.style.overflow || "";
        savedBodyOverflow = body.style.overflow || "";
        document.documentElement.style.overflow = "hidden";
        body.style.overflow = "hidden";
      } else if (mobileLock) {
        mobileLock = false;
        document.documentElement.style.overflow = savedHtmlOverflow;
        body.style.overflow = savedBodyOverflow;
      }
      return;
    }

    if (on) {
      savedScrollX = window.scrollX;
      savedScrollY = window.scrollY;
      var bStyle = window.getComputedStyle(body);
      savedBodyTop = body.style.top || "";
      savedBodyLeft = body.style.left || "";
      savedBodyWidth = body.style.width || "";
      body.classList.add("is-tour-active");
      body.style.top = -savedScrollY + "px";
      body.style.left = -savedScrollX + "px";
      body.style.width = "100%";
    } else {
      body.classList.remove("is-tour-active");
      body.style.top = savedBodyTop;
      body.style.left = savedBodyLeft;
      body.style.width = savedBodyWidth;
      window.scrollTo(savedScrollX, savedScrollY);
    }
  }

  function mountOverlay() {
    if (overlayMounted) return;
    var parent = overlay.parentElement;
    if (parent && parent !== document.body) {
      document.body.appendChild(overlay);
    }
    overlayMounted = true;
  }

  function $sel(sel) {
    return document.querySelector(sel);
  }

  function viewport() {
    if (window.visualViewport) {
      return {
        w: window.visualViewport.width,
        h: window.visualViewport.height,
        offX: window.visualViewport.offsetLeft,
        offY: window.visualViewport.offsetTop,
      };
    }
    return {
      w: document.documentElement.clientWidth || window.innerWidth,
      h: document.documentElement.clientHeight || window.innerHeight,
      offX: 0,
      offY: 0,
    };
  }

  function targetRectFor(t) {
    if (!t || isHidden(t) || t.offsetWidth === 0) return null;
    var r = t.getBoundingClientRect();
    var v = viewport();
    return {
      left: r.left + v.offX,
      top: r.top + v.offY,
      width: r.width,
      height: r.height,
      right: r.right + v.offX,
      bottom: r.bottom + v.offY,
    };
  }

  function targetRect(step) {
    if (!step || !step.target) return null;
    var t = document.querySelector(step.target);
    if (!t || isHidden(t) || t.offsetWidth === 0) return null;
    return targetRectFor(t);
  }

  function cacheEls() {
    if (overlay) return;
    overlay = $sel("#tourOverlay");
    panelT = $sel("#tourPanelT");
    panelB = $sel("#tourPanelB");
    panelL = $sel("#tourPanelL");
    panelR = $sel("#tourPanelR");
    highlight = $sel("#tourHighlight");
    arrow = $sel("#tourArrow");
    shaftW = $sel("#tourArrowShaftW");
    shaft = $sel("#tourArrowShaft");
    card = $sel("#tourCard");
    titleEl = $sel("#tourTitle");
    descEl = $sel("#tourDesc");
    indicator = $sel("#tourStepIndicator");
    prevBtn = $sel("#tourPrev");
    nextBtn = $sel("#tourNext");
    skipBtn = $sel("#tourSkip");

    prevBtn.addEventListener("click", function () {
      if (index > 0) {
        index -= 1;
        render();
      }
    });
    nextBtn.addEventListener("click", function () {
      if (index < total - 1) {
        index += 1;
        render();
      } else {
        finish();
      }
    });
    skipBtn.addEventListener("click", finish);
    document.addEventListener("keydown", onKey);
  }

  function onKey(e) {
    if (!overlay || overlay.hidden) return;
    if (e.key === "Escape") finish();
    if (e.key === "ArrowRight" && index < total - 1) {
      index += 1;
      render();
    }
    if (e.key === "ArrowLeft" && index > 0) {
      index -= 1;
      render();
    }
  }

  function isHidden(elm) {
    while (elm) {
      if (elm.hidden) return true;
      if (elm.hasAttribute && elm.hasAttribute("hidden")) return true;
      var st = window.getComputedStyle(elm);
      if (st.display === "none" || st.visibility === "hidden") return true;
      elm = elm.parentElement;
    }
    return false;
  }

  function findVisibleStep(fromIndex) {
    var i = fromIndex, tries = 0;
    while (tries < total) {
      var s = MENUS[activeMenu][i];
      var t = s && s.target ? document.querySelector(s.target) : null;
      if (t && !isHidden(t) && t.offsetWidth > 0) return i;
      i = (i + 1) % total;
      tries += 1;
    }
    return fromIndex;
  }

  function scrollTargetIntoView(elm) {
    if (!elm) return;
    var v = viewport();
    var r = elm.getBoundingClientRect();
    var inView = r.top >= v.offY && r.bottom <= v.offY + v.h;
    if (inView) return;

    var p = elm.parentElement;
    while (p && p !== document.body && p !== document.documentElement) {
      var st = window.getComputedStyle(p);
      var overflowY = st.overflowY || st.overflow || "";
      if (overflowY === "auto" || overflowY === "scroll") {
        var rElm = elm.getBoundingClientRect();
        var rP = p.getBoundingClientRect();
        if (rElm.top < rP.top || rElm.bottom > rP.bottom) {
          p.scrollTop += (rElm.top - rP.top) - 16;
        }
        return;
      }
      p = p.parentElement;
    }
    if (isMobileViewport()) {
      var scrollRoot = document.scrollingElement || document.documentElement;
      var targetTop = scrollRoot.scrollTop + (r.top - v.offY) - 16;
      scrollRoot.scrollTop = targetTop;
      return;
    }
    window.scrollTo({
      top: window.scrollY + (r.top - v.offY) - 16,
      behavior: "instant"
    });
  }

  function clamp(v, a, b) {
    return Math.max(a, Math.min(b, v));
  }

  function placeCard(tr, cw, ch) {
    var v = viewport();
    var vw = v.w;
    var vh = v.h;
    var pad = 14;
    var gap = 12;
    var margin = 10;

    var tLeft = tr.left + v.offX;
    var tTop = tr.top + v.offY;
    var tRight = tr.right + v.offX;
    var tBottom = tr.bottom + v.offY;

    var bottomFree = vh - tBottom;
    var topFree = tTop;
    var side = "bottom";
    var cardTop = tBottom + gap;
    var cardLeft = clamp(tLeft + tr.width / 2 - cw / 2, margin, vw - cw - margin);

    var overlaps = function (l, t) {
      return l < tRight + margin && l + cw > tLeft - margin &&
             t < tBottom + margin && t + ch > tTop - margin;
    };

    if (bottomFree < ch + gap + pad) {
      if (topFree >= ch + gap + pad) {
        side = "top";
        cardTop = tTop - ch - gap;
        cardLeft = clamp(tLeft + tr.width / 2 - cw / 2, margin, vw - cw - margin);
      } else {
        var leftFree = tLeft - cw - gap;
        var rightFree = vw - tRight - cw - gap;
        if (leftFree >= rightFree) {
          side = "left";
          cardLeft = Math.max(margin, leftFree);
          cardTop = clamp(tTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
        } else {
          side = "right";
          cardLeft = Math.min(vw - cw - margin, tRight + gap);
          cardTop = clamp(tTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
        }
      }
    }

    if (overlaps(cardLeft, cardTop)) {
      var lf = tLeft - cw - gap;
      var rf = vw - tRight - cw - gap;
      if (lf >= rf) {
        side = "left";
        cardLeft = Math.max(margin, lf);
        cardTop = clamp(tTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
      } else {
        side = "right";
        cardLeft = Math.min(vw - cw - margin, rf);
        cardTop = clamp(tTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
      }
    }

    return { side: side, top: cardTop, left: cardLeft };
  }

  function render() {
    if (!activeMenu) return;
    var i = findVisibleStep(index);
    if (i !== index) index = i;
    var step = MENUS[activeMenu][index];
    var t = step && step.target ? document.querySelector(step.target) : null;

    titleEl.textContent = step.title;
    descEl.textContent = step.desc;
    indicator.textContent = "Langkah " + (index + 1) + " dari " + total;
    prevBtn.hidden = index === 0;
    nextBtn.textContent = index === total - 1 ? "Selesai" : "Lanjut";
    renderProgress();

    var tr = t ? targetRectFor(t) : null;

    if (!t || !isElementVisible(t) || !tr) {
      card.style.left = "50%";
      card.style.top = "50%";
      card.style.transform = "translate(-50%, -50%)";
      card.style.margin = "";
      card.classList.add("tour-card--centered");
      [panelT, panelB, panelL, panelR].forEach(function (p) {
        if (p) p.style.display = "none";
      });
      highlight.style.display = "none";
      arrow.style.display = "none";
      return;
    }

    card.classList.remove("tour-card--centered");

    var cw = card.offsetWidth || 300;
    var ch = card.offsetHeight || 200;
    var v = viewport();
    var vw = v.w;
    var vh = v.h;

    var pLeft = tr.left + v.offX;
    var pTop = tr.top + v.offY;
    var pRight = tr.right + v.offX;
    var pBottom = tr.bottom + v.offY;

    var gap = 12;
    var pad = 14;
    var margin = 10;

    var bottomFree = vh - pBottom;
    var topFree = pTop;
    var side = "bottom";
    var cardTop = pBottom + gap;
    var cardLeft = clamp(pLeft + tr.width / 2 - cw / 2, margin, vw - cw - margin);

    var overlaps = function (l, t) {
      return l < pRight + margin && l + cw > pLeft - margin &&
             t < pBottom + margin && t + ch > pTop - margin;
    };

    if (bottomFree < ch + gap + pad) {
      if (topFree >= ch + gap + pad) {
        side = "top";
        cardTop = pTop - ch - gap;
        cardLeft = clamp(pLeft + tr.width / 2 - cw / 2, margin, vw - cw - margin);
      } else {
        var leftFree = pLeft - cw - gap;
        var rightFree = vw - pRight - cw - gap;
        if (leftFree >= rightFree) {
          side = "left";
          cardLeft = Math.max(margin, leftFree);
          cardTop = clamp(pTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
        } else {
          side = "right";
          cardLeft = Math.min(vw - cw - margin, pRight + gap);
          cardTop = clamp(pTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
        }
      }
    }

    if (overlaps(cardLeft, cardTop)) {
      var lf = pLeft - cw - gap;
      var rf = vw - pRight - cw - gap;
      if (lf >= rf) {
        side = "left";
        cardLeft = Math.max(margin, lf);
        cardTop = clamp(pTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
      } else {
        side = "right";
        cardLeft = Math.min(vw - cw - margin, rf);
        cardTop = clamp(pTop + tr.height / 2 - ch / 2, pad, vh - ch - pad);
      }
    }

    var pos = { side: side, top: cardTop, left: cardLeft };

    card.style.transform = "none";
    card.style.left = pos.left + "px";
    card.style.top = pos.top + "px";
    card.style.margin = "";

    // Scroll target into view only when the step actually changed AND the
    // target is not already visible. Body scroll is locked while the tour
    // runs, so we only scroll the innermost container that actually
    // contains the target; otherwise the page would shift under the card.
    var stepKey = activeMenu + ":" + index;
    if (stepKey !== lastStepKey) {
      lastStepKey = stepKey;
      var r0 = t.getBoundingClientRect();
      var v0 = viewport();
      var inView = r0.top >= v0.offY && r0.bottom <= v0.offY + v0.h;
      if (!inView) {
        scrollTargetIntoView(t);
        clearTimeout(window.__enkTourScrollT);
        window.__enkTourScrollT = setTimeout(scheduleRender, 40);
      }
    }

    var spotlightGap = 8;
    var x0 = pLeft - spotlightGap;
    var y0 = pTop - spotlightGap;
    var w0 = tr.width + spotlightGap * 2;
    var h0 = tr.height + spotlightGap * 2;

    if (panelT) {
      panelT.style.display = "block";
      panelT.style.left = "0";
      panelT.style.right = "0";
      panelT.style.top = "0";
      panelT.style.height = Math.max(0, y0) + "px";
    }
    if (panelB) {
      panelB.style.display = "block";
      panelB.style.left = "0";
      panelB.style.right = "0";
      panelB.style.top = (y0 + h0) + "px";
      panelB.style.bottom = "0";
      panelB.style.height = "";
    }
    if (panelL) {
      panelL.style.display = "block";
      panelL.style.left = "0";
      panelL.style.top = y0 + "px";
      panelL.style.height = h0 + "px";
      panelL.style.width = Math.max(0, x0) + "px";
      panelL.style.right = "";
    }
    if (panelR) {
      panelR.style.display = "block";
      panelR.style.top = y0 + "px";
      panelR.style.height = h0 + "px";
      panelR.style.right = "0";
      panelR.style.left = (x0 + w0) + "px";
      panelR.style.width = "";
    }

    highlight.style.display = "block";
    highlight.style.left = pLeft - 2 + "px";
    highlight.style.top = pTop - 2 + "px";
    highlight.style.width = tr.width + 4 + "px";
    highlight.style.height = tr.height + 4 + "px";

    arrow.style.display = "block";
    arrow.setAttribute("width", String(vw));
    arrow.setAttribute("height", String(vh));
    arrow.setAttribute("viewBox", "0 0 " + vw + " " + vh);
    arrow.style.left = "0";
    arrow.style.top = "0";

    var cardRect = {
      left: pos.left,
      top: pos.top,
      right: pos.left + cw,
      bottom: pos.top + ch,
    };
    var targetRect = {
      left: pLeft,
      top: pTop,
      right: pRight,
      bottom: pBottom,
    };

    var sx0, sy0, ex, ey;
    if (cardRect.top >= targetRect.bottom) {
      sx0 = (cardRect.left + cardRect.right) / 2;
      sy0 = cardRect.top;
      ex = (targetRect.left + targetRect.right) / 2;
      ey = targetRect.bottom;
    } else if (cardRect.bottom <= targetRect.top) {
      sx0 = (cardRect.left + cardRect.right) / 2;
      sy0 = cardRect.bottom;
      ex = (targetRect.left + targetRect.right) / 2;
      ey = targetRect.top;
    } else if (cardRect.left >= targetRect.right) {
      sx0 = cardRect.left;
      sy0 = (cardRect.top + cardRect.bottom) / 2;
      ex = targetRect.right;
      ey = (targetRect.top + targetRect.bottom) / 2;
    } else if (cardRect.right <= targetRect.left) {
      sx0 = cardRect.right;
      sy0 = (cardRect.top + cardRect.bottom) / 2;
      ex = targetRect.left;
      ey = (targetRect.top + targetRect.bottom) / 2;
    } else {
      sx0 = (cardRect.left + cardRect.right) / 2;
      sy0 = (cardRect.top + cardRect.bottom) / 2;
      ex = (targetRect.left + targetRect.right) / 2;
      ey = (targetRect.top + targetRect.bottom) / 2;
    }

    var d = "M " + sx0 + " " + sy0 + " L " + ex + " " + ey;
    shaft.setAttribute("d", d);
    shaftW.setAttribute("d", d);
  }

  function renderProgress() {
    var p = $sel("#tourProgress");
    if (!p) return;
    p.innerHTML = "";
    for (var i = 0; i < total; i++) {
      var dot = document.createElement("span");
      dot.className = "tour-progress-dot" +
        (i === index ? " is-active" : i < index ? " is-done" : "");
      p.appendChild(dot);
    }
  }

  function lockScroll(on) {
    if (on === bodyLock) return;
    bodyLock = on;
    lockPage(on);

    if (on) {
      var targets = [];

      if (activeMenu === "receiver") {
        var list = document.querySelector("#receiverMessageList");
        if (list) targets.push(list);
      }

      var selectors = [
        ".commander-sent-scroll",
        ".receiver-chat-list-body",
        ".receiver-message-container",
        ".main-content",
        "#appLayout",
        "main",
      ];
      selectors.forEach(function (sel) {
        document.querySelectorAll(sel).forEach(function (elm) {
          targets.push(elm);
        });
      });

      targets.forEach(function (elm) {
        lockElement(elm, true);
      });
    } else {
      document.querySelectorAll("[data-tour-locked]").forEach(function (elm) {
        lockElement(elm, false);
      });
    }
  }

  function start(menu) {
    cacheEls();
    mountOverlay();
    activeMenu = menu || "commander";
    total = MENUS[activeMenu].length;
    index = 0;
    lastStepKey = "";

    // On a narrow screen the spotlight/arrow overlay is hidden; the card is
    // pinned to the bottom. To keep each step readable we simply scroll the
    // current target into view before locking the page.
    var firstStep = MENUS[activeMenu] && MENUS[activeMenu][0];
    if (firstStep && firstStep.target) {
      var firstTarget = document.querySelector(firstStep.target);
      if (firstTarget && isElementVisible(firstTarget)) {
        if (isMobileViewport()) {
          scrollTargetIntoView(firstTarget);
        } else {
          window.scrollTo({ top: 0, behavior: "instant" });
        }
      }
    }

    overlay.hidden = false;
    overlay.classList.add("is-open");
    lockScroll(true);
    render();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", onResize);
    }
    card.focus({ preventScroll: true });
  }

  function onWheel(e) {
    if (document.body.classList.contains("is-tour-active")) {
      e.preventDefault();
    }
  }

  function onTouchMove(e) {
    if (document.body.classList.contains("is-tour-active")) {
      e.preventDefault();
    }
  }

  function onScroll() {
    scheduleRender();
  }
  function onResize() {
    scheduleRender();
  }

  function finish() {
    if (!overlay || overlay.hidden) return;
    if (activeMenu) {
      try {
        localStorage.setItem(MENU_KEYS[activeMenu], "1");
      } catch (e) {}
    }
    lockScroll(false);
    overlay.hidden = true;
    overlay.classList.remove("is-open");
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("scroll", onScroll, true);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("wheel", onWheel);
    window.removeEventListener("touchmove", onTouchMove);
    if (window.visualViewport) {
      window.visualViewport.removeEventListener("resize", onResize);
    }
    activeMenu = null;
  }

  function menuDone(menu) {
    try {
      return localStorage.getItem(MENU_KEYS[menu]) === "1";
    } catch (e) {
      return false;
    }
  }

  function activeView() {
    var el2 = document.querySelector(".view-section.active");
    if (!el2) return null;
    var id = el2.id || "";
    if (id.indexOf("commander") !== -1) return "commander";
    if (id.indexOf("members") !== -1) return "members";
    if (id.indexOf("receiver") !== -1) return "receiver";
    return null;
  }

  window.CypherTour = {
    startForMenu: start,
    isDone: menuDone,
    MENU_KEYS: MENU_KEYS,
  };

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("btnGuide");
    var authGate = document.getElementById("authGate");

    if (authGate) {
      var observer = new MutationObserver(function () {
        var isLogin = !authGate.hidden;
        if (btn) btn.hidden = isLogin;
        if (isLogin && !menuDone("login")) {
          clearTimeout(window.__enkTourTimer);
          window.__enkTourTimer = setTimeout(function () {
            start("login");
          }, 500);
        } else {
          clearTimeout(window.__enkTourTimer);
        }
      });
      observer.observe(authGate, { attributes: true, attributeFilter: ["hidden"] });
    }

    if (btn) {
      btn.addEventListener("click", function () {
        var menu = activeView() || "login";
        start(menu);
      });
    }

    if (authGate && !authGate.hidden && btn) {
      btn.hidden = true;
      if (!menuDone("login")) {
        window.__enkTourTimer = setTimeout(function () {
          start("login");
        }, 500);
      }
    }
  });
})();
