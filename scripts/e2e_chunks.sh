#!/usr/bin/env bash
# Run the FULL `-m e2e` suite as foreground chunks.
#
# WHY CHUNKS. The whole suite takes ~27 minutes, the Bash tool auto-backgrounds
# anything past a 10-minute ceiling, and backgrounded runs in this environment were
# killed three times within seconds of starting. Chunks each finish inside the
# ceiling, so nothing is backgrounded and nothing gets reaped.
#
# Coverage is the same 565 tests: the chunks below partition every file that
# `-m e2e --collect-only` reports, including the three under notifications/tests/
# that no `tests/test_e2e_*.py` glob would reach.
#
# Usage: bash scripts/e2e_chunks.sh [chunk-number]   (no argument = all chunks)
set -u

C1="tests/test_e2e_text_colour.py tests/test_link_apply.py tests/test_link_dialog_behaviour.py tests/test_table_grid_algebra.py"

C2="notifications/tests/test_e2e_bell.py notifications/tests/test_e2e_email_prefs.py notifications/tests/test_e2e_notifications.py tests/test_e2e_alignment.py tests/test_e2e_analytics.py tests/test_e2e_auth.py tests/test_e2e_builder.py tests/test_e2e_builder_authoring.py tests/test_e2e_builder_filter.py tests/test_e2e_builder_reorder.py tests/test_e2e_builder_toggle.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_builder_ws2.py"

C3="tests/test_e2e_catalog.py tests/test_e2e_choice_editor_feedback.py tests/test_e2e_choice_inline_feedback.py tests/test_e2e_choicegrid.py tests/test_e2e_course_form.py tests/test_e2e_courses.py tests/test_e2e_editor.py tests/test_e2e_editor_preview_state_regression.py tests/test_e2e_editor_unit_token.py tests/test_e2e_editor_view_toggle.py tests/test_e2e_editor_ws3.py tests/test_e2e_error_pages.py tests/test_e2e_favicon.py tests/test_e2e_fillgate.py tests/test_e2e_gallery.py tests/test_e2e_grouping.py"

C4="tests/test_e2e_filltable.py tests/test_e2e_guessnumber.py tests/test_e2e_html_element.py tests/test_e2e_imagezoom.py tests/test_e2e_inline_rename.py tests/test_e2e_link_dialog.py tests/test_e2e_markdone.py tests/test_e2e_math_input.py tests/test_e2e_media_picker.py tests/test_e2e_multigrid.py tests/test_e2e_notes.py tests/test_e2e_people.py"

C5="tests/test_e2e_practice_state.py tests/test_e2e_question_restore.py tests/test_e2e_questions.py tests/test_e2e_questions_2b.py tests/test_e2e_questions_2d.py tests/test_e2e_questions_2dii.py tests/test_e2e_questions_2diii.py tests/test_e2e_quiz.py tests/test_e2e_quiz_finish.py tests/test_e2e_quiz_math.py tests/test_e2e_quiz_previewer.py tests/test_e2e_results.py tests/test_e2e_reveal_gate.py tests/test_e2e_review.py tests/test_e2e_scroll_affordance.py tests/test_e2e_settings.py tests/test_e2e_settings_5c.py tests/test_e2e_setup_5e.py"

C6="tests/test_e2e_slideshow.py tests/test_e2e_smoke.py tests/test_e2e_spanning_merge.py tests/test_e2e_spanning_roundtrip.py tests/test_e2e_sso_5d.py tests/test_e2e_stepper.py tests/test_e2e_subjects.py tests/test_e2e_switchgate.py tests/test_e2e_switchgrid.py tests/test_e2e_table_editor.py tests/test_e2e_tabs.py tests/test_e2e_tags.py tests/test_e2e_tags_notes_hub.py tests/test_e2e_transfer.py tests/test_e2e_twocolumn.py tests/test_e2e_unit_crumbs.py tests/test_e2e_unit_head_layout.py tests/test_e2e_unit_nav.py tests/test_e2e_wide_content_scroll.py tests/test_e2e_widget_restore.py tests/test_tabs_editor_dnd.py"

run_chunk() {
  local n="$1"; shift
  echo "=========== CHUNK ${n} ==========="
  uv run pytest -m e2e -n 4 -q --verbosity=0 --create-db "$@" \
    > "/tmp/e2e_chunk${n}.txt" 2>&1
  local rc=$?
  tail -2 "/tmp/e2e_chunk${n}.txt" | head -1
  echo "chunk ${n} exit=${rc}  retries_fired=$(grep -c 'deadlocked (attempt' "/tmp/e2e_chunk${n}.txt")  teardown_errors=$(grep -c 'ERROR at teardown' "/tmp/e2e_chunk${n}.txt")"
  return $rc
}

want="${1:-all}"
fail=0
for n in 1 2 3 4 5 6; do
  [ "$want" != "all" ] && [ "$want" != "$n" ] && continue
  eval "files=\$C${n}"
  run_chunk "$n" $files || fail=1
done
echo "=========== done (fail=${fail}) ==========="
exit $fail
