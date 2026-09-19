(function () {
  "use strict";

  // Fallback for browsers without CSS `field-sizing: content` (courses.css grows an
  // editable fill-in blank natively where it is supported): size each editable
  // blank to its value so typed text never scrolls out of view. courses.css keeps
  // the 8ch minimum and the 100% maximum, which clamp this inline width too.
  // Locked (read-only) blanks are left alone: their `size` + :read-only rules
  // already fit the answer.
  if (window.CSS && CSS.supports && CSS.supports("field-sizing", "content")) return;

  var SELECTOR = 'input.question__blank-input[type="text"]';
  var canvas = document.createElement("canvas");

  function fit(inp) {
    if (inp.readOnly) return;
    var s = getComputedStyle(inp);
    var ctx = canvas.getContext("2d");
    ctx.font = s.font;
    var text = ctx.measureText(inp.value).width;
    var chrome =
      parseFloat(s.paddingLeft) + parseFloat(s.paddingRight) +
      parseFloat(s.borderLeftWidth) + parseFloat(s.borderRightWidth);
    // +2px leaves room for the caret after the last character.
    inp.style.width = Math.ceil(text + chrome + 2) + "px";
  }

  function fitAll(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll(SELECTOR), fit);
  }

  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches(SELECTOR)) fit(e.target);
  });

  // Blanks re-rendered with a value (a checked question's swapped form, the
  // editor's preview fragments) arrive without an input event.
  var pending = false;
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () {
      pending = false;
      fitAll();
    });
  }).observe(document.body, { childList: true, subtree: true });

  fitAll();
})();
