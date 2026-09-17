# Analytics drill-down

The analytics matrix starts with one column per top-level section of your
course, but the real power is in *drilling down*: opening a column into its
children and narrowing the grid to just the students you care about. Open the
matrix from the **Teaching** panel on your dashboard — click **Analytics**
next to a course — or from **My groups & collections**, where each group
card carries an **Analytics** link scoped to that group. Collection cards
carry one too, when you can review that collection's course.

![A student's results page](static:core/img/help/drill-down.en.png)

## Expanding a column

Any column header that has children below it is shown as a link with a small
**▸** marker after its title. Click it to expand that column in place — a part
opens into its chapters, a chapter into its units, and so on. The header row
grows a second, nested band that spans the new child columns.

- You can expand **several columns at once**, and each child can be expanded
  again, as deep as the course structure goes.
- An expanded group header carries a **✕ Collapse** link. Click it to fold the
  group back to a single column.
- The expansion state lives in the page address (as repeated `expand=` values),
  so a drilled-down view is **bookmarkable and shareable** — send a colleague a
  link and they see exactly the columns you opened.

Because colour bands are computed per course, a cell means the same thing before
and after you expand it — drilling down never changes the scale.

## Selecting a subset of students

Each student row has a checkbox, and the header has a **Select all students**
box. Tick the students you want and press **Apply selection**: the matrix
recomputes for just that subset, so the averages reflect only the students you
chose. This is ideal for checking a study group, or for comparing a handful of
students on one chapter.

- A small badge shows how many students are selected, e.g. **3 selected**.
- While a subset is active, a **Show all** link appears — use it to clear the
  subset and return to the whole roster.
- Changing the **Students** scope dropdown starts a fresh view and discards the
  current subset, so the scope you pick and the subset you tick never conflict.

Your expand and subset choices travel with you: they round-trip across the
Progress ↔ Results toggle and the Export link, so you never lose your place
when switching what the matrix measures.

## Results and progress

Click a student's name to open their page for the current course. It opens in
the same view as the matrix you came from, and the heading names that view and
the student. A **Progress / Results** switch under the heading changes the view
without going back:

- **Progress** lists every lesson and quiz. A finished lesson carries a ✓, an
  unfinished one an empty ○, and a lesson that is not required is tagged
  **Additional**. Chapter headings count the required lessons done, as
  **lessons: 1/2**.
- **Results** is a table of the quizzes and of the parts, chapters and sections
  that contain them. A quiz with a score shows its marks and percentage; any
  other quiz shows its status, and one awaiting review links to the review page.
  Every heading that holds more than one quiz shows on its own row a quiz
  fraction such as **1/3**, and, once at least one of them is marked, the
  summed marks and the percentage; **Whole course** at the top does the same
  for the whole course. The fraction counts
  the quizzes whose score is included in the sum out of all the quizzes in that
  section, so a quiz still awaiting review is not included yet. The sums and the
  colours of the percentages are the analytics matrix's own, so a heading row
  matches that section's cell in the Results matrix.

The **← Analytics** link restores the exact scope, mode, expanded columns and
subset you came from, so you can dip into one student and pop straight back to
the same grid.

## Per-question answers

On a student's results page, the title of every quiz they have started is a
link. Click it to see that quiz question by question: the student's answer, the
answer key where theirs was wrong, the marks, and how many attempts they used.
A choice question lists **every** option, marking what the student chose and
which options are correct; a question with several parts lines the student's
answers and the key up in columns. A quiz still in progress shows the answers
given so far. A question waiting for your review links straight to the review
page. The **← Results** or **← Progress** link (it names the view you came
from) takes you back with your analytics view unchanged.

## Related topics

- [The analytics matrix](analytics)
- [Gradebook export](gradebook-export)
- [Quiz review](quiz-review)
