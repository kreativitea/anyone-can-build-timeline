// glass.js: liquid-glass Part B. Three small touches on the glass:
//   1. the lens: the rim of the bar and of "3 new posts" bends what is behind
//      it, like the edge of thick glass (only in browsers that can draw it);
//   2. the light: the sheen on the glass follows the mouse, and lights up
//      where you press;
//   3. the tab pill: the current view's pill slides to the tab you choose.
// It only adds. The page works the same without it (the CSS already has the
// plain look), so everything here is inside try ... catch.
// No numbers live here: they are tokens in tokens.css, read with getComputedStyle.
"use strict";

(function () {
  const SVG = "http://www.w3.org/2000/svg";
  const GLASS = ".glass, .top-bar, .menu[open] > ul";   // every piece of glass
  const LENSED = ".top-bar, .new-posts";                 // the glass that bends (at most two kinds)
  let lensCount = 0;   // gives each lens filter its own id: lens-1, lens-2, ...
  let filters = null;  // the hidden <svg> that holds the filters

  // A media query the computer answers ("does it ask for less motion?").
  function asks(query) {
    return window.matchMedia(query).matches;
  }

  // A number token, like --lens-bezel: 14px, read as 14.
  function token(name) {
    return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
  }

  // ---- 1. The lens ----

  // True only when this browser really draws an SVG filter behind an element.
  // @supports alone is not trusted: some browsers say yes and then draw nothing
  // behind the glass at all. Chromium (Chrome, Edge, Brave, Arc, Opera) is the
  // one that draws it, and only Chromium has navigator.userAgentData.
  // Never when the computer asks for less transparency or more contrast.
  function glassCanRefract() {
    return Boolean(navigator.userAgentData) &&
      window.CSS && CSS.supports("backdrop-filter", "url(#lens) blur(1px)") &&
      !asks("(prefers-reduced-transparency: reduce)") &&
      !asks("(prefers-contrast: more)") &&
      !asks("(forced-colors: active)");
  }

  // How much the glass bends light at `t`: 1 at its very edge, where it
  // curves most, down to 0 where the rim ends and the glass is flat. A soft
  // curve (not a straight line), so the bend fades smoothly into the flat
  // middle. (A "squircle" profile bends only the outer 2 or 3 pixels, and the
  // frost then blurs that away.)
  function bend(t) {
    return (1 - t) * (1 - t);
  }

  // The map that tells the browser how far to move each pixel behind the glass:
  // red is left/right, green is up/down, 128 means "do not move". Inside the
  // rim (`bezel` pixels from the edge), each pixel shows what is a little
  // further in, toward the middle of the shape, most at the very edge: what is
  // behind seems to curve over the edge, as through the rim of thick glass.
  // The shape is a rectangle with round corners of `radius` (a capsule when
  // the radius is half the height). Returns the picture as a data URL.
  function lensMap(width, tall, radius, bezel) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = tall;
    const context = canvas.getContext("2d");
    const picture = context.createImageData(width, tall);
    const r = Math.min(radius, width / 2, tall / 2);
    for (let y = 0; y < tall; y += 1) {
      for (let x = 0; x < width; x += 1) {
        // Where this pixel is, from the middle, and how far past the straight
        // part of the edge (qx, qy), to find its distance to the edge.
        const px = x + 0.5 - width / 2;
        const py = y + 0.5 - tall / 2;
        const qx = Math.abs(px) - (width / 2 - r);
        const qy = Math.abs(py) - (tall / 2 - r);
        let distance;   // from this pixel to the edge, inside the shape
        let nx = 0;     // the direction out of the shape, here
        let ny = 0;
        if (qx > 0 && qy > 0) {
          const corner = Math.hypot(qx, qy);
          distance = r - corner;
          nx = Math.sign(px) * qx / corner;
          ny = Math.sign(py) * qy / corner;
        } else if (qx > qy) {
          distance = r - qx;
          nx = Math.sign(px);
        } else {
          distance = r - qy;
          ny = Math.sign(py);
        }
        let push = 0;   // how far to move, from 0 (not at all) to 1 (the most)
        if (distance >= 0 && distance < bezel) {
          push = bend(distance / bezel);
        }
        const at = (y * width + x) * 4;
        picture.data[at] = Math.round(128 - 127 * nx * push);       // red
        picture.data[at + 1] = Math.round(128 - 127 * ny * push);   // green
        picture.data[at + 2] = 128;
        picture.data[at + 3] = 255;
      }
    }
    context.putImageData(picture, 0, 0);
    return canvas.toDataURL();
  }

  // The hidden <svg> that holds every lens filter, made once.
  function filterHolder() {
    if (!filters) {
      filters = document.createElementNS(SVG, "svg");
      filters.setAttribute("width", "0");
      filters.setAttribute("height", "0");
      filters.setAttribute("aria-hidden", "true");
      filters.style.position = "absolute";
      document.body.prepend(filters);
    }
    return filters;
  }

  // Makes one lens filter for `element`, and keeps its map the element's own
  // size: drawn again when the element changes size (at most once every
  // 100 milliseconds while it keeps changing). Moving or scrolling never
  // draws it again.
  function fitLens(element) {
    lensCount += 1;
    const id = "lens-" + lensCount;
    const filter = document.createElementNS(SVG, "filter");
    filter.setAttribute("id", id);
    filter.setAttribute("filterUnits", "userSpaceOnUse");
    filter.setAttribute("primitiveUnits", "userSpaceOnUse");
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    // Without sRGB, the browser reads the map's colours in another colour
    // space, and 128 would no longer mean "do not move".
    filter.setAttribute("color-interpolation-filters", "sRGB");
    const map = document.createElementNS(SVG, "feImage");
    map.setAttribute("x", "0");
    map.setAttribute("y", "0");
    map.setAttribute("preserveAspectRatio", "none");
    map.setAttribute("result", "map");
    const bend = document.createElementNS(SVG, "feDisplacementMap");
    bend.setAttribute("in", "SourceGraphic");
    bend.setAttribute("in2", "map");
    bend.setAttribute("xChannelSelector", "R");
    bend.setAttribute("yChannelSelector", "G");
    filter.append(map, bend);
    filterHolder().append(filter);
    element.style.setProperty("--lens", "url(#" + id + ")");

    let lastSize = "";
    function draw() {
      const width = Math.round(element.offsetWidth);
      const tall = Math.round(element.offsetHeight);
      if (width === 0 || tall === 0 || width + "x" + tall === lastSize) {
        return;   // hidden ("3 new posts" while there are none), or the same size
      }
      lastSize = width + "x" + tall;
      const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 0;
      for (const box of [filter, map]) {
        box.setAttribute("width", String(width));
        box.setAttribute("height", String(tall));
      }
      bend.setAttribute("scale", String(token("--lens-scale")));
      map.setAttribute("href", lensMap(width, tall, radius, token("--lens-bezel")));
    }
    let waiting = null;
    new ResizeObserver(function () {
      clearTimeout(waiting);
      waiting = setTimeout(draw, lastSize ? 100 : 0);
    }).observe(element);
    draw();
  }

  // Turns the lens on or off as the computer's settings change.
  function updateRefracts() {
    document.documentElement.classList.toggle("refracts", glassCanRefract());
  }

  function startLens() {
    if (!glassCanRefract()) {
      // Still listen: if the settings change, the lens may come on.
      for (const query of ["(prefers-reduced-transparency: reduce)", "(prefers-contrast: more)"]) {
        window.matchMedia(query).addEventListener("change", startLensOnce);
      }
      return;
    }
    startLensOnce();
  }

  let lensStarted = false;
  function startLensOnce() {
    if (lensStarted) {
      updateRefracts();
      return;
    }
    if (!glassCanRefract()) {
      return;
    }
    lensStarted = true;
    for (const element of document.querySelectorAll(LENSED)) {
      fitLens(element);
    }
    // The filters exist before the class is set, so no glass is ever left without one.
    updateRefracts();
    for (const query of ["(prefers-reduced-transparency: reduce)", "(prefers-contrast: more)"]) {
      window.matchMedia(query).addEventListener("change", updateRefracts);
    }
  }

  // ---- 2. The light ----

  // Follows the mouse over the glass: --light-x and --light-y on the piece of
  // glass under it, at most once per screen frame, on one element at a time.
  // Only for a mouse or a trackpad (not a touch screen), and never when the
  // computer asks for less motion. Pressing lights the glass up (.is-pressed).
  function followLight() {
    let lit = null;       // the glass the light is on now
    let pressed = null;   // the glass being pressed now
    let point = null;     // the last pointer place, waiting for the next frame
    let frame = 0;

    function allowed() {
      return asks("(hover: hover) and (pointer: fine)") && !asks("(prefers-reduced-motion: reduce)");
    }

    function rest(glass) {
      if (glass) {
        glass.classList.remove("is-lit");
        glass.style.removeProperty("--light-x");
        glass.style.removeProperty("--light-y");
      }
    }

    function place() {
      frame = 0;
      const glass = point && point.target instanceof Element ? point.target.closest(GLASS) : null;
      if (glass !== lit) {
        rest(lit);
        lit = glass;
      }
      if (!glass) {
        return;
      }
      const box = glass.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) {
        return;
      }
      const x = ((point.clientX - box.left) / box.width) * 100;
      const y = ((point.clientY - box.top) / box.height) * 100;
      glass.style.setProperty("--light-x", x.toFixed(1) + "%");
      glass.style.setProperty("--light-y", y.toFixed(1) + "%");
      glass.classList.add("is-lit");
    }

    document.addEventListener("pointermove", function (event) {
      if (event.pointerType !== "mouse" || !allowed()) {
        return;
      }
      point = event;
      if (!frame) {
        frame = requestAnimationFrame(place);
      }
    }, { passive: true });

    document.addEventListener("pointerdown", function (event) {
      if (event.pointerType !== "mouse" || !allowed() || !(event.target instanceof Element)) {
        return;
      }
      pressed = event.target.closest(GLASS);
      if (pressed) {
        pressed.classList.add("is-pressed");
      }
    }, { passive: true });

    function letGo() {
      if (pressed) {
        pressed.classList.remove("is-pressed");
        pressed = null;
      }
    }
    document.addEventListener("pointerup", letGo, { passive: true });
    document.addEventListener("pointercancel", letGo, { passive: true });
    document.documentElement.addEventListener("pointerleave", function () {
      letGo();
      rest(lit);
      lit = null;
    });
  }

  // ---- 3. The tab pill ----

  // One pill under a row of tabs (.tabs), always under the current one
  // (aria-current="page", or aria-pressed="true"). It watches the row, so
  // app.js's showView needs no change. The pill slides in CSS; with less
  // motion, the durations are 0s and it jumps.
  function moveTabPill(nav) {
    function place() {
      const current = nav.querySelector(
        ':scope > button[aria-current="page"], :scope > button[aria-pressed="true"]');
      if (nav.hidden || !current || current.offsetWidth === 0) {
        nav.classList.remove("has-pill");
        return;
      }
      // The class first: it makes the row the place the tabs are measured from.
      nav.classList.add("has-pill");
      nav.style.setProperty("--pill-x", current.offsetLeft + "px");
      nav.style.setProperty("--pill-y", current.offsetTop + "px");
      nav.style.setProperty("--pill-width", current.offsetWidth + "px");
      nav.style.setProperty("--pill-height", current.offsetHeight + "px");
    }
    new MutationObserver(place).observe(nav, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-current", "aria-pressed", "hidden"],
    });
    // The words in a tab can change (another language), and the row can wrap.
    new ResizeObserver(place).observe(nav);
    place();
  }

  // ---- Start ----

  function startGlass() {
    for (const step of [startLens, followLight, function () {
      for (const nav of document.querySelectorAll(".tabs")) {
        moveTabPill(nav);
      }
    }]) {
      try {
        step();
      } catch (error) {
        // One touch failing never stops the others, or the page.
      }
    }
  }

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", startGlass);
    } else {
      startGlass();
    }
  } catch (error) {
    // The page works without glass.js.
  }
})();
