I guess the only thing I will not need from the packt app is chat. Below there is a brief descriptions of what I want from my app which I do not find in the packt app. 

1. Metrics measured. For each student certain values are recorded measured per course.
   1. Progress - which says only how much of the course or its part a student has viewed.
   1. Results - from quizes.
   1. Attempts - in quizes, per question.
1. Course depth
   1. I want this course to be potentially deepr, at most: course > part > chapter >  section > unit > element.
   1. Each of: part, chapter,  section can be skipped, course, unit and element are obligatory.
1. Unit 
   1. Unit is what a student sees in a single screen, with a possible exception for quizes (see below).
   1. Unit can be either a lesson or a quiz.
   1. Unit consists of whatever number of elements. They are displayed  as block elements in a single page. Exception: elements in a quiz with slideshow option on.
   1. Lesson allows all element types, but if quiz elements are used, the performance/ results are not recorded
   1. Quiz allows quiz element types only, but the performance is recorded.
   1. A unit can be obligatory (default) 
   1. For each unit and each student, progress is recorded: 0-1. 0 means the student did not even start the unit. 1 means they viewed all elements of the unit.
1. Lesson elements:
   1. Text with styling options 
   1. Image with optional figcaption 
   1. Video from whitelisted domains or uploaded as a file
   1. Iframe (e.g. the following must be accepted: GeoGebra ...)
   1. HTML
   1. Math block
1. Lesson elements - images and videos
   1. Course Admins are allowed to add files to platform storage. There is a whitelist of file types - images and videos.
   1. When adding an element with an kmage or a video, the course admin may:
      1. use a file from the storage, 
      1. browse and choose a file from their device,
      1. drag and drop a file.
1. Lesson element- HTML
   1. A Course Admin may add an HTML string that will be shown adequately in the unit, preserving the roles of the tags.
   1. The HTML will accept standard LaTeX / MathJax notation, both block and inline.
   1. A Course Admin may add two files that would work for all HTML elements throughout the course: a single CSS file and a single JS file.
   1. All HTML elements from the course will be styled according to the CSS file within the element tag. 
   1. The Java Script code from the JS file will be applied to all HTML elements from the unit.
   1. For each unit / lesson, an additional JS file valid for this unit will be stored. Its aim will be to give initial values to some variables so that the main JS file will work correctly.
   1. If you need to inspect exemplary CSS, JS and HTML files that I used in a different e-learning platform, I will happily provide them.
1. Quiz
   1. After submitting an answer in a quiz element it is by default automatically marked.
   1. A course admin can set a quiz or a quiz element (question) as not marked automatically. The options for marking type are:
      1. [A] automatically marked (default)
      1. [N] not marked
      1. [R] requires review
   1. Quiz [A] may contain questions of type [A] or [N].
   1. Quiz [N] may contain only questions [N].
   1. Quiz [R] may contain questions of all types.
   1. When a quiz admin wants to set a type of question which is not allowed in the quiz they are prompted if they want to change the quiz type.
   1. An admin can set a max number of marks for each question (default 1)
   1. An admin can set a max number of attempts a user can try to answer a quiz question. By default it is not restricted (infinite). The number of times a student attempts a question is recorded.
1. Quiz elements
   1. Multiple choice question with one correct answer
   1. Multiple choice question with many correct answers
   1. Fill in the blanks
   1. Fill in the blanks given answers (drag n drop them). There can be more potential available answers than the blanks.
   1. Short response - an admin adds accepted answers.
   1. Short numerical response - an admin adds accepted answer and accepted error. E.g. if accepted answer is 1.2 and accepted error is 0.03, all answers in the range from 1.17 to 1.23 will be accepted. Also, both "." and "," can be used as a decimal point.
   1. Extended response
      1. An admin can add key words that need to appear in the response (if they give N of them and if a student misses 1 in the answer, their score is (N-1)/N)
      1. An admin can add key words that must not appear in the response.
   1. Match pairs
   1. Drag and drop pieces to an image. The pieces are either words / phrases or other images. 
      1. Use case 1. Biology. A drawing of a human body, a student needs to label its parts.
      1. Use case 2. Language. Categorise verbs: plural vs singular and past vs present vs future: place each verb in a 2 by 3 grid. Alternatively: "categorise" can be a different question type.
1. Per user notes
   1. When a user reads and interacts with a lesson / unit, they should be able to click or tap somewhere in the unit, to add a note there. "There" could be a paragraph or a block html tag. 
   1. A note is just a plain text, no formatting. 
   1. In the unit added notes need to be visible. On desktop they can be shown in the margin. On mobile - maybe an icon at the end of the tag where the note was added?
   1. When a student checks the course outline, on each level of the course, if there are any notes in respective part, the number should be visible for the student, so that they can easily find where they left notes.
1. Per user tags
   1. A user should be able to add tags to a unit.
   1. They should be able to easily remove a tag from a unit.
   1. They should be able to remove entirely a tag not assigned to any unit.
   1. They should be able to "filter" units by tags.

 
