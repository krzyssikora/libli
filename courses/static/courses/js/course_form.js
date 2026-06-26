// Progressive enhancement for the course form: the self-enrolment cohorts field
// only matters when Visibility = "Open", so reveal it only then. Without JS the
// field stays visible (it is inert when the course is "Assigned").
(function () {
  function init() {
    var vis = document.getElementById("id_visibility");
    var row = document.querySelector('[data-field="self_enroll_cohorts"]');
    if (!vis || !row) return;
    function sync() {
      row.hidden = vis.value !== "open";
    }
    vis.addEventListener("change", sync);
    sync();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
