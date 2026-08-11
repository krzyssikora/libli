#!/usr/bin/env bash
# Run the FULL `-m e2e` suite as foreground chunks.
#
# WHY CHUNKS. The Bash tool auto-backgrounds anything past a 10-minute ceiling,
# and backgrounded runs in this environment were killed three times within
# seconds of starting. Chunks each finish inside the ceiling, so nothing is
# backgrounded and nothing gets reaped.
#
# COVERAGE IS CHECKED, NOT CLAIMED. An earlier version of this file asserted a
# fixed test count in a comment and silently drifted to covering 84 of 97 files
# -- omitting test_e2e_math_reflow_dom.py's 171 tests, a fifth of the suite, so
# "I ran the full e2e suite" was false by that much. `verify_coverage` below now
# runs before every full run and fails loudly on any mismatch. Run it alone with:
#
#     bash scripts/e2e_chunks.sh check
#
# Usage: bash scripts/e2e_chunks.sh [chunk-number|check]   (no argument = all)
set -u

C1="tests/test_e2e_text_colour.py tests/test_link_apply.py tests/test_link_dialog_behaviour.py tests/test_table_grid_algebra.py"

C2="notifications/tests/test_e2e_bell.py notifications/tests/test_e2e_email_prefs.py notifications/tests/test_e2e_notifications.py tests/test_e2e_alignment.py tests/test_e2e_analytics.py tests/test_e2e_auth.py tests/test_e2e_before_after.py tests/test_e2e_builder.py tests/test_e2e_builder_authoring.py tests/test_e2e_builder_filter.py tests/test_e2e_builder_reorder.py tests/test_e2e_builder_toggle.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_builder_ws2.py tests/test_e2e_callout_container.py"

C3="tests/test_e2e_catalog.py tests/test_e2e_choice_editor_feedback.py tests/test_e2e_choice_inline_feedback.py tests/test_e2e_choicegrid.py tests/test_e2e_clipboard.py tests/test_e2e_course_form.py tests/test_e2e_courses.py tests/test_e2e_depth3.py tests/test_e2e_editor.py tests/test_e2e_editor_force_open.py tests/test_e2e_editor_preview_state_regression.py tests/test_e2e_editor_row_layout.py tests/test_e2e_editor_scroll_containment.py tests/test_e2e_editor_unit_token.py tests/test_e2e_editor_view_toggle.py tests/test_e2e_editor_ws3.py tests/test_e2e_error_pages.py tests/test_e2e_favicon.py tests/test_e2e_fillblank_lock.py tests/test_e2e_fillgate.py tests/test_e2e_gallery.py tests/test_e2e_grouping.py"

C4="tests/test_e2e_filltable.py tests/test_e2e_guessnumber.py tests/test_e2e_html_element.py tests/test_e2e_image_size.py tests/test_e2e_imagezoom.py tests/test_e2e_inline_rename.py tests/test_e2e_link_dialog.py tests/test_e2e_markdone.py tests/test_e2e_math_input.py tests/test_e2e_math_reflow.py tests/test_e2e_media_picker.py tests/test_e2e_multigrid.py tests/test_e2e_notes.py tests/test_e2e_people.py"

C5="tests/test_e2e_practice_state.py tests/test_e2e_publish_toggle.py tests/test_e2e_question_restore.py tests/test_e2e_questions.py tests/test_e2e_questions_2b.py tests/test_e2e_questions_2d.py tests/test_e2e_questions_2dii.py tests/test_e2e_questions_2diii.py tests/test_e2e_quiz.py tests/test_e2e_quiz_finish.py tests/test_e2e_quiz_math.py tests/test_e2e_quiz_previewer.py tests/test_e2e_quote_block.py tests/test_e2e_results.py tests/test_e2e_reveal_gate.py tests/test_e2e_review.py tests/test_e2e_review_shell_isolation.py tests/test_e2e_scroll_affordance.py tests/test_e2e_settings.py tests/test_e2e_settings_5c.py tests/test_e2e_setup_5e.py"

C6="tests/test_e2e_slide_overflow.py tests/test_e2e_slideshow.py tests/test_e2e_smoke.py tests/test_e2e_spanning_merge.py tests/test_e2e_spanning_roundtrip.py tests/test_e2e_spoiler_rule.py tests/test_e2e_sso_5d.py tests/test_e2e_stepper.py tests/test_e2e_subjects.py tests/test_e2e_switchgate.py tests/test_e2e_switchgrid.py tests/test_e2e_table_cell_images.py tests/test_e2e_table_editor.py tests/test_e2e_tabs.py tests/test_e2e_tags.py tests/test_e2e_tags_notes_hub.py tests/test_e2e_transfer.py tests/test_e2e_twocolumn.py tests/test_e2e_unit_crumbs.py tests/test_e2e_unit_head_layout.py tests/test_e2e_unit_nav.py tests/test_e2e_wide_content_scroll.py tests/test_e2e_widget_restore.py tests/test_tabs_editor_dnd.py"

# Its own chunk: 171 tests, ~20% of the selection, and it takes no `live_server`
# so it pays no TRUNCATE -- fast but bulky, and it does not belong bolted onto
# a chunk of ordinary browser tests.
C7="tests/test_e2e_math_reflow_dom.py"

NCHUNKS=7

# Every file the chunks name, one per line.
chunk_files() {
  local n
  for n in $(seq 1 "$NCHUNKS"); do
    eval "printf '%s\n' \$C${n}"
  done
}

# Fail loudly if the chunks no longer partition the real selection.
verify_coverage() {
  local collected chunked missing extra
  collected=$(uv run python -m pytest -m e2e --collect-only -q 2>/dev/null \
    | tr -d '\r' | grep -E '\.py: [0-9]+$' | sed 's/: [0-9]*$//' | sort -u)
  chunked=$(chunk_files | sort -u)

  missing=$(comm -23 <(echo "$collected") <(echo "$chunked"))
  extra=$(comm -13 <(echo "$collected") <(echo "$chunked"))

  if [ -n "$missing" ] || [ -n "$extra" ]; then
    echo "!!! CHUNK COVERAGE IS STALE -- refusing to claim a full run." >&2
    [ -n "$missing" ] && { echo "collected but NOT in any chunk:" >&2; echo "$missing" >&2; }
    [ -n "$extra" ]   && { echo "in a chunk but NOT collected:" >&2;   echo "$extra" >&2; }
    echo "Fix the C1..C${NCHUNKS} lists above, then re-run." >&2
    return 1
  fi

  echo "coverage ok: $(echo "$chunked" | wc -l | tr -d ' ') files partitioned across ${NCHUNKS} chunks"
}

run_chunk() {
  local n="$1"; shift
  echo "=========== CHUNK ${n} ==========="
  # KEEP `--verbosity=0`. `addopts` already carries `-q`, so the `-q` below
  # would make it `-qq` and suppress the warnings summary -- which is exactly
  # where the two counters at the bottom of this function read from. The
  # explicit --verbosity=0 comes last and resets verbosity to 0, so the
  # summary survives. Verified. Remove it and both counters silently read 0.
  uv run pytest -m e2e -n 4 -q --verbosity=0 --create-db "$@" \
    > "/tmp/e2e_chunk${n}.txt" 2>&1
  local rc=$?
  # Grep the result line rather than `tail -2 | head -1`: that assumed the
  # summary was always second-to-last and printed the pytest docs URL instead
  # whenever a warnings summary followed it. `tr -d '\r'` is required -- the
  # logs are CRLF here, so an anchored `$` never matches without it.
  tr -d '\r' < "/tmp/e2e_chunk${n}.txt" \
    | grep -E '^=+ .*(passed|failed|error|no tests ran).*=+$' | tail -1 \
    || echo "(no pytest summary line -- see /tmp/e2e_chunk${n}.txt)"
  echo "chunk ${n} exit=${rc}  retries_fired=$(grep -c 'deadlocked (attempt' "/tmp/e2e_chunk${n}.txt")  teardown_errors=$(grep -c 'ERROR at teardown' "/tmp/e2e_chunk${n}.txt")"
  return $rc
}

want="${1:-all}"

if [ "$want" = "check" ]; then
  verify_coverage
  exit $?
fi

# Only a full run claims full coverage, so only a full run has to prove it.
if [ "$want" = "all" ]; then
  verify_coverage || exit 1
fi

fail=0
for n in $(seq 1 "$NCHUNKS"); do
  [ "$want" != "all" ] && [ "$want" != "$n" ] && continue
  eval "files=\$C${n}"
  run_chunk "$n" $files || fail=1
done
echo "=========== done (fail=${fail}) ==========="
exit $fail
