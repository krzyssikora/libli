# Reversible data migration: route the mat-pp course html_css onto the app design
# tokens so its sandboxed HTML-element content follows the app light/dark theme.
# Colour-only rewrite; see docs/superpowers/plans/2026-07-08-theme-aware-html-element-sandbox.md
# (Task 5). CSS values are embedded as string literals (no runtime file IO at replay);
# the committed courses/migrations/_mat_pp_baseline/*.txt files are the auditable source.
from django.db import migrations

# Paste of _mat_pp_baseline/html_css.txt (original mat-pp html_css):
OLD_CSS = r""":root {
    /* dimensions */
    --navbar-height: 40px;
    --section-header-height: 60px;
    --section-height: calc(100vh - var(--navbar-height) - var(--scrollbar-width));
    --items-padding: 10px;
    --standard-margin-padding: 10px;
    --new-matrix-button-height: 45px;
    --scrollbar-width: 6px;
    --corner-radius: 10px;
    /* colours */
    --colour-light-blue: #a3d1fd;
    --colour-light-background: #f7f7f7;
    /* --colour-blue-border: #0075b4; */
    --colour-blue-border: #88cafe;
    --colour-light-green: rgba(0,255,0,0.2);
    --colour-light-red: rgba(255,0,0,0.2);
  }



/* edx */
.sequence-container {
    width: 100%!important;
}
/* end edx */
.centered {
    text-align: center;
}
.justified {
    text-align: justify;
}

.lesson_info {
    width: 90%;
    margin: 10px;
}
.lesson_info_head, .lesson_info ol, .lesson_info ul {
    padding-top: 10px!important;
    padding-bottom: 10px!important;
    padding-left: 40px!important;
    padding-right: 40px!important;
    border: 1px solid gray;
    border-radius: 10px;
    margin: 10px!important;
    background-color: var(--colour-light-background);
}

.lesson_info_head {
    font-weight: bold;
}

.lesson_info_body>ol, .lesson_info_body>ul {
    background-color: #eeeeee;
}

.lesson_info li {
    line-height: 1.6;
}

.lesson_info li a {
    text-decoration: none;
}

.lesson_info li a:hover {
    background-color: lightgray;
    color: navy;
}

details > summary {
    list-style-type: '▷ ';
}
details {
    width: 94%;
    margin-left: 3%;
}

details[open] > summary {
    list-style-type: '▽ ';
}

details[open] {
    border: lightgray 1px solid;
    border-radius: 5px;
    padding: 5px;
}

.lesson_info ol>li ul>li, .inner_lesson_info {
     list-style-type: '▹';
}

.back_to_contents {
    width: 90%;
    padding: 10px 40px;
    border: 1px solid gray;
    border-radius: 10px;
    /* margin: 10px auto; */
}

.back_to_contents a {
    text-decoration: none;
}

.back_to_contents a:hover {
    background-color: lightgray;
    color: blue;
}
        
h2 {
    font-weight: bolder;
}

.my_table_border, .my_table_noborder {
    border-collapse: collapse;
    margin: 0 auto;
    background-color: white;
}
.my_table_noborder.transparent {
    border-collapse: collapse;
    margin: 0 auto;
    background-color: transparent;
}
.my_table_border th,.my_table_border td {
    border: 1px solid gray;
    text-align: center;
    vertical-align: middle!important;
    padding: 5px;
}
.my_table_noborder th,.my_table_noborder td {
    border: none!important;
    text-align: center;
    vertical-align: middle!important;
    padding: 5px;
}
.my_table_border.left th,.my_table_border.left td {
    border: 1px solid gray;
    text-align: left;
    vertical-align: middle!important;
    padding: 5px;
}
.my_table_noborder.left th,.my_table_noborder.left td {
    border: none!important;
    text-align: left;
    vertical-align: middle!important;
}

.my_table_TL, .my_table_TL_80 {
    border-collapse: collapse;
    min-width: 100%;
}
.my_table_TL img, .my_table_TL_80 img {
    max-width: none!important;
}
.my_table_TL td, .my_table_TL th {
    width: fit-content!important;
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid gray!important;
    padding: 5px 10px!important;
    text-align: left;
    vertical-align: top;
}
.my_table_TL_80 td, .my_table_TL_80 th {
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid gray!important;
    padding: 5px 10px!important;
    text-align: left;
    vertical-align: top;
}
.my_table_TL_80 td:nth-of-type(1), .my_table_TL_80 th:nth-of-type(1) {
    width: 80%;
}
.my_table_TC, .my_table_TC_80 {
    border-collapse: collapse;
    min-width: 100%;
}
.my_table_TC img, .my_table_TC_80 img {
    max-width: none!important;
}
.my_table_TC td, .my_table_TC th {
    width: fit-content!important;
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid gray!important;
    padding: 5px 10px!important;
    text-align: center;
    vertical-align: top;
}
.my_table_TC_80 td, .my_table_TC_80 th {
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid gray!important;
    padding: 5px 10px!important;
    text-align: center;
    vertical-align: top;
}
.my_table_TC_80 td:nth-of-type(1), .my_table_TC_80 th:nth-of-type(1) {
    width: 80%;
}

.my_table_CL {
    border-collapse: collapse;
    min-width: 100%;
}
.my_table_CL td, .my_table_CL th {
    width: fit-content!important;
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid gray!important;
    padding: 5px 10px!important;
    text-align: left;
    vertical-align: middle;
}


.my_table_xy {
    border-collapse: collapse;
}
.my_table_xy tr >td {
    padding: 5px;
    text-align: center;
    border-left: 1px solid black;
    border-right: 1px solid black;
}
.my_table_xy tr >td:first-of-type {
    border-left: none;
}
.my_table_xy tr >td:last-of-type {
    border-right: none;
}
.my_table_xy tr:first-of-type >td {
    border-top: none;
    border-bottom: 1px solid black;
}
.my_table_xy tr:last-of-type >td {
    border-top: 1px solid black;
    border-bottom: none;
}


table td.no_border_td {
    border: none!important;
    text-align: center;
}
.my_table_left td, .my_table_left th{
    text-align: left;    
}
.table_centered {
    margin-left: auto;
    margin-right: auto;
}
table.cells_centered td, table.cells_centered th {
    text-align: center;
}
table.cells_right td, table.cells_right th {
    text-align: right;
}

.vertical_table td, .vertical_table th {
    border-left: 3px solid gray!important;
    border-right: 3px solid gray!important;
}
.vertical_table img {
    padding: 0 20px!important;
    max-width: 250px!important;
    min-width: 150px!important;
}
.narrow_table, .narrow_table tr {
    width: 1%!important;
}
.narrow_table td, .narrow_table th {
    width: 1%; 
    white-space: nowrap;
}


.table_input {
    text-align: center;
    width: 80px;
}
.table_input_30 {
    text-align: center;
    width: 30px;
    padding-left: 3px!important;
    padding-right: 3px!important;
}
.table_input_50 {
    text-align: center;
    width: 50px;
    padding-left: 3px!important;
    padding-right: 3px!important;
}
.success {
    color: darkgreen;
    font-weight: bold;
    background-color: lightgray;
    border-radius: 4px;
    display: block;
    margin: 5px 0;
    padding: 5px;
}
.failure {
    color: red;
    font-weight: bold;
    background-color: lightgray;
    border-radius: 4px;
    display: block;
    margin: 5px 0;
    padding: 5px;
}
.ans_warning {
    color: orangered;
    font-weight: bold;
    background-color: lightgray;
    border-radius: 4px;
    display: block;
    margin: 5px 0;
    padding: 5px;
}
.hidden {
    display: none!important;
}
.visible {
    display: block;
}
.coordinate {
    display: inline-block;
}
.ks_example {
    background-image: linear-gradient(to bottom, var(--colour-light-blue), transparent);
    border: 1px solid var(--colour-light-blue);
    border-radius: 5px;
    padding: 5px 8px;
    margin: 5px 0;
}
.question, .example, .question_like {
    color: rgb(2, 42, 135);
    font-weight: bold;
    font-size: large;
    padding: 5px 8px;
}
.question_text {
    color: #202060;
    background-color: rgb(243, 243, 243);
    font-style: italic;
    padding: 5px;
}
div[id^=question] {
    border: 1px solid;
    border-radius: 5px;
    border-image-source: linear-gradient(
        0deg,
        lightgray 0%,
        transparent 80%
      );
    border-image-slice: 1;
    padding: 5px 8px;
    margin: 5px 3px;
}
.myequation {
    background-color: var(--colour-light-blue);
    border-radius: 5px;
    padding: 5px 8px;
}
.important {
    background-color: lightgray;
    border: 2px solid var(--colour-blue-border);
    border-radius: 5px;
    padding: 5px 8px;
    margin: 3px 0;
}
span.show_next {
    display: inline-block;
}
.confirmTF, .confirm_choice, .confirm_multiple, 
.confirm_feedback_multiple, .show_solution, 
.show_next, .fill_show_next, .show_slides,
.any_button, .confirm_button_feedback,
.switch_confirm, .just_button {
    width: fit-content;
    color: white;
    background-color: var(--colour-blue-border);
    text-align: center;
    padding: 5px 10px;
    margin: 5px 5px 5px 0;
    border-radius: 5px;
    border: 1px solid var(--colour-blue-border);
}

.confirmTF:hover, .confirm_choice:hover, .confirm_multiple:hover, .confirm_feedback_multiple:hover, 
.show_solution:hover, .show_next:hover, .fill_show_next:hover, .show_slides,.any_button:hover, 
.confirm_button_feedback,.switch_confirm:hover, .just_button:hover {
    cursor: pointer;
}

.switch_show_next {
    display: inline-block;
    width: fit-content;
    color: white;
    background-color: var(--colour-blue-border);
    padding: 1px 3px;
    margin: 0 2px;
    border-radius: 5px;
    border: 1px solid var(--colour-blue-border);
}
.inline_button {
    display: inline-block;
    width: fit-content;
    color: var(--colour-blue-border);
    background-color: white;
    text-align: center;
    padding: 5px 10px;
    margin: 5px 5px 5px 0;
    border-radius: 5px;
    border: 1px solid var(--colour-blue-border);
}
.inline_warning {
    display: inline-block;
    width: fit-content;
    color: orangered;
    background-color: white;
    text-align: center;
    padding: 5px 10px;
    margin: 5px 5px 5px 0;
    border-radius: 5px;
    border: 1px solid orangered;
}
.inline_block {
    display: inline-block;
}
.ks_button:hover {
    cursor: pointer;
}
.ks_binary_choices {
    border-top: 1px solid lightgray;
}
.one_choice {
    display: inline-block;
    width: 150px;
    background-color: white;
    color: gray;
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
    border: 1px solid gray;
}
.one_choice.on {
    background-color: gray;
    color: white;
}
.one_choice_50 {
    width: 50px;
}
.truth, .false {
    display: inline-block;
    /* width: 50px; */
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
}
.truth {
    color: green;
    border: 1px solid green;
    background-color: rgba(0,255,0,0.02);
}
.truth.chosen {
    color: white;
    background-color: green;
}
.false {
    color: red;
    border: 1px solid red;
    background-color: rgba(255,0,0,0.02);
}
.false.chosen {
    color: white;
    background-color: red;
}
.correct_answer {
    border: 4px solid green!important;
    border-radius: 4px;
}
.wrong_answer {
    border: 4px solid red!important;
    border-radius: 4px;
}
.no_answer {
    border: 1px solid gray;
    border-radius: 4px;
}
.white_grey_button, .white_gray_button {
    display: inline-block;
    width: 150px;
    background-color: white;
    color: gray;
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
    border: 1px solid gray;
}
.white_grey_button.chosen, .white_gray_button.chosen {
    background-color: gray;
    color: white;
}

.multi_many_ans, .multi_ans {
    display: inline-block;
    width: 150px;
    background-color: white;
    color: gray;
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
    border: 1px solid gray;   
}
.multi_many_ans.chosen, .multi_ans.chosen {
    background-color: gray;
    color: white;
}
.multi_many_option {
    display: inline-block;
    background-color: white;
    color: gray;
    text-align: center;
    padding: 2px;
    margin: 2px;
}
.mult_option {
    width: 50%;
    border: 1px solid darkgray;
    border-radius: 3px;
    padding: 3px;
    margin: 5px;
    background-color: none;
}
.mult_option.chosen {
    background-color: lightgray;
}
.multiple_option {
    margin: 5px;
}
.multiple_option > div.inline {
    display: inline-block;
    vertical-align: middle;
}
.mult_feedback_incorrect {
    width: 50%;
    color: red;
    border: 1px solid lightgray;
    background-color: lightgray;
    border-radius: 3px;
    padding: 3px;
    margin: 5px;
}
[id^="mult_choice"] {
    width: 1.5em;
    height: 1.5em;
}
.lightgreen {
    background-color: var(--colour-light-green);
}
.lightred {
    background-color: var(--colour-light-red);
}
/* tabs */
.ks_tabs {
    width: 90%;
    margin: auto;
}
.ks_tabs > div {
    padding: 15px;
    background-color: #eaeaea;
    transition: opacity 200ms linear;
    display: none;
}
.ks_tabs > div.visible {
    display: block;
}
.ks_tabs > ul {
    text-align: center;
    list-style-type: none!important;
    display: flex;
    padding: 0!important;
    margin: 0!important;
}
.ks_tabs > ul > li {
    min-width: 30%;
    font-size: large;
    font-weight: bold;
    padding: 5px 5px 0 0;
    margin: 0!important;
}
.ks_tabs > ul > li > a {
    display: block;
    height: 2em;
    margin-right: 5px;
    padding-top: 5px;
    background-color: lightgray;
    color: #333;
    text-decoration: none;
    border-radius: 3px 3px 0 0;
    overflow: hidden;
    position: relative;
    bottom: 0;
}
.ks_tabs > ul > li > a.chosen {
    background-color: #eaeaea;
    color: blue;
}
.mark_done {
    border: none;
    padding: 5px;
    display: inline-block;
    width: fit-content;
    height: fit-content;
    background-color: white;
    user-select: none;
}

.mark_done.on {
    background-color: gray;
}
ul:has(div.statement), .nolist {
    list-style-type: none!important;
}
.statement {
    display: inline-block;
    border-bottom: 1px solid gray;
    height: fit-content!important;
}

.question_solution, .question_answer {
    margin-top: 10px;
}
.replaced {
    border: 1px solid green!important;
    border-radius: 4px;
    text-align: center;
    display: inline-block;
    line-height: 2em;
}
/* slide show */
.arrows {
    display: block;
    height: 100px;
    width: 100%;
    position: relative;
}
.container_slide_title {
    position: absolute;
    left: 10%;
    width: 80%;
    display: flex;
    justify-content: center;
    align-items: center;
    margin-left: auto;
    margin-right: auto;
    height: 100px;
}
.slide_container {
    left: 10%;
    width: 80%;
    display: flex;
    justify-content: center;
    align-items: center;
    margin-left: auto;
    margin-right: auto;
    /* height: fit-content; */
}
.container_arrow {
    position: absolute;
    width: 10%;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 80px;
}
.container_arrow_left {
    left: 0;
}
.container_arrow_right {
    right: 0;
}
.slide_container > img {
    object-fit: cover;
}
.arrow_left {
    position: absolute;
    top: 0;
    left: 0;
    margin: auto;
}
.arrow_right {
    position: absolute;
    top: 0;
    right: 0;
    margin: auto;
}

.two_columns {
    width: 100%;
    margin: 0 auto;
}
.left_column {
    float: left;
    width: 49%;
}
.right_column {
    float: right;
    width: 49%;
}
.after_columns {
    content: none;
    display: table;
    clear: both;
}
.switch_line {
    padding: 5px 0;
    vertical-align: middle;
}
.switch_around {
    padding: 5px;
    display: inline-block;
    border: 2px none;
    height: 2em;
    width: fit-content;
}
.switch_value {
    padding: 5px;
    border-radius: 2px;
    cursor: pointer;
    border-width: 2px;
    border-style: solid;
    /* height: 2em!important; */
    height: fit-content!important;
    width: fit-content;
    margin-bottom: -0.7em;
}
.switch_value.progress {
    display: inline-block;
    border-color: blue;
}
.switch_value.correct {
    border-color: green;
}
details>summary {
    margin-bottom: 10px;
    cursor: pointer;
}
details>summary>h3, details>summary>h4 {
    display: inline-block;
}
sup {
    top: -1.5em!important;
}

blockquote {
    font-style: italic;
    padding-left: 20px;
    font-size: 110%;
}

.list15 li {
    margin-bottom: 1.5em;
}

.fbox {
    border: gray 1pt solid;
    display: inline-block;
    padding: 3px;
}

ul.bold > li::marker, ol.bold > li::marker {
    font-weight: bold;
}

ul.bold > li, ol.bold > li {
    padding-left: 5px;
}

.border_red_thin {
    border: 1px solid red;
    padding: 5px;
}
.border_blue_thin {
    border: 1px solid var(--colour-blue-border);
    padding: 5px;
}
.red_on_yellow {
    color: red;
    background-color: yellow;
}
.blue_on_green {
    color: blue;
    background-color: rgb(130, 200, 130);
}

.magenta_on_gray {
    color: magenta;
    background-color: lightgray;
}
.yellow_on_gray {
    color: yellow;
    background-color: lightgray;
}

.rounded_corners {
    border-radius: var(--corner-radius);
}

.table_wrapper {
    overflow: auto;
}

.iframe_zonk {
    background-color: rgb(165, 192, 243);
    color: rgb(121, 5, 5);
    padding: 1rem;
}
.iframe_small {
    background-color: lightgray;
    border: 2px solid darkorange;
    border-radius: 1rem;
    padding: .5rem;
}
figure:has(embed) {
    position: relative; 
    width: 100%; 
    height: 0; 
    padding-bottom: 56.25%;
}
figure > embed {
    position: absolute; 
    width: 100%; 
    height:100%;
}
figure {
    text-align: center;
}
figure > img {
    max-width: 100%;
}
figure > figcaption {
    font-style: italic;
    font-size: smaller;
}
figure > video {
    max-width: 1000px;
}

.slidecontainer {
    width: 60%; /* Width of the outside container */
    margin:0 auto;
  }
/* The slider itself */
.slider {
    -webkit-appearance: none;  /* Override default CSS styles */
    appearance: none;
    width: 100%;
    height: 15px; /* Specified height */
    background: #d3d3d3; /* Grey background */
    outline: none; /* Remove outline */
    opacity: 0.7; /* Set transparency (for mouse-over effects on hover) */
    -webkit-transition: .2s; /* 0.2 seconds transition on hover */
    transition: opacity .2s;
}
/* Mouse-over effects */
.slider:hover {
    opacity: 1; /* Fully shown on mouse-over */
  }
  
  /* The slider handle (use -webkit- (Chrome, Opera, Safari, Edge) and -moz- (Firefox) to override default look) */
  .slider::-webkit-slider-thumb {
    -webkit-appearance: none; /* Override default look */
    appearance: none;
    width: 15px; /* Set a specific slider handle width */
    height: 15px; /* Slider handle height */
    background: var(--colour-light-blue); 
    cursor: pointer; /* Cursor on hover */
  }
  
  .slider::-moz-range-thumb {
    width: 15px; /* Set a specific slider handle width */
    height: 15px; /* Slider handle height */
    background: var(--colour-light-blue); 
    cursor: pointer; /* Cursor on hover */
  }


  .ks_tooltip {
    border: thin solid lightgray;
    border-radius: .2rem;
    padding: .2rem;
    text-decoration: underline;
  }

.clearfix::after {
    content: "";
    display: block;
    clear: both;
}"""

# Paste of _mat_pp_baseline/html_css_themed.txt (themed mat-pp html_css):
NEW_CSS = r"""html,body{background:var(--surface-raised);color:var(--text-primary)}
:root{color-scheme:light}
@media(prefers-color-scheme:dark){:root{color-scheme:dark}}
:root[data-theme="dark"]{color-scheme:dark}
:root[data-theme="light"]{color-scheme:light}

:root {
    /* dimensions */
    --navbar-height: 40px;
    --section-header-height: 60px;
    --section-height: calc(100vh - var(--navbar-height) - var(--scrollbar-width));
    --items-padding: 10px;
    --standard-margin-padding: 10px;
    --new-matrix-button-height: 45px;
    --scrollbar-width: 6px;
    --corner-radius: 10px;
    /* colours (routed onto app design tokens) */
    --colour-light-blue: var(--primary-subtle);
    --colour-light-background: var(--surface-sunken);
    /* --colour-blue-border: #0075b4; */
    --colour-blue-border: var(--primary);
    --colour-light-green: var(--success-subtle);
    --colour-light-red: var(--danger-subtle);
  }



/* edx */
.sequence-container {
    width: 100%!important;
}
/* end edx */
.centered {
    text-align: center;
}
.justified {
    text-align: justify;
}

.lesson_info {
    width: 90%;
    margin: 10px;
}
.lesson_info_head, .lesson_info ol, .lesson_info ul {
    padding-top: 10px!important;
    padding-bottom: 10px!important;
    padding-left: 40px!important;
    padding-right: 40px!important;
    border: 1px solid var(--border-default);
    border-radius: 10px;
    margin: 10px!important;
    background-color: var(--colour-light-background);
}

.lesson_info_head {
    font-weight: bold;
}

.lesson_info_body>ol, .lesson_info_body>ul {
    background-color: var(--surface-sunken);
}

.lesson_info li {
    line-height: 1.6;
}

.lesson_info li a {
    text-decoration: none;
}

.lesson_info li a:hover {
    background-color: var(--surface-sunken);
    color: var(--primary);
}

details > summary {
    list-style-type: '▷ ';
}
details {
    width: 94%;
    margin-left: 3%;
}

details[open] > summary {
    list-style-type: '▽ ';
}

details[open] {
    border: var(--border-default) 1px solid;
    border-radius: 5px;
    padding: 5px;
}

.lesson_info ol>li ul>li, .inner_lesson_info {
     list-style-type: '▹';
}

.back_to_contents {
    width: 90%;
    padding: 10px 40px;
    border: 1px solid var(--border-default);
    border-radius: 10px;
    /* margin: 10px auto; */
}

.back_to_contents a {
    text-decoration: none;
}

.back_to_contents a:hover {
    background-color: var(--surface-sunken);
    color: var(--primary);
}
        
h2 {
    font-weight: bolder;
}

.my_table_border, .my_table_noborder {
    border-collapse: collapse;
    margin: 0 auto;
    background-color: var(--surface-raised);
}
.my_table_noborder.transparent {
    border-collapse: collapse;
    margin: 0 auto;
    background-color: transparent;
}
.my_table_border th,.my_table_border td {
    border: 1px solid var(--border-default);
    text-align: center;
    vertical-align: middle!important;
    padding: 5px;
}
.my_table_noborder th,.my_table_noborder td {
    border: none!important;
    text-align: center;
    vertical-align: middle!important;
    padding: 5px;
}
.my_table_border.left th,.my_table_border.left td {
    border: 1px solid var(--border-default);
    text-align: left;
    vertical-align: middle!important;
    padding: 5px;
}
.my_table_noborder.left th,.my_table_noborder.left td {
    border: none!important;
    text-align: left;
    vertical-align: middle!important;
}

.my_table_TL, .my_table_TL_80 {
    border-collapse: collapse;
    min-width: 100%;
}
.my_table_TL img, .my_table_TL_80 img {
    max-width: none!important;
}
.my_table_TL td, .my_table_TL th {
    width: fit-content!important;
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid var(--border-default)!important;
    padding: 5px 10px!important;
    text-align: left;
    vertical-align: top;
}
.my_table_TL_80 td, .my_table_TL_80 th {
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid var(--border-default)!important;
    padding: 5px 10px!important;
    text-align: left;
    vertical-align: top;
}
.my_table_TL_80 td:nth-of-type(1), .my_table_TL_80 th:nth-of-type(1) {
    width: 80%;
}
.my_table_TC, .my_table_TC_80 {
    border-collapse: collapse;
    min-width: 100%;
}
.my_table_TC img, .my_table_TC_80 img {
    max-width: none!important;
}
.my_table_TC td, .my_table_TC th {
    width: fit-content!important;
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid var(--border-default)!important;
    padding: 5px 10px!important;
    text-align: center;
    vertical-align: top;
}
.my_table_TC_80 td, .my_table_TC_80 th {
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid var(--border-default)!important;
    padding: 5px 10px!important;
    text-align: center;
    vertical-align: top;
}
.my_table_TC_80 td:nth-of-type(1), .my_table_TC_80 th:nth-of-type(1) {
    width: 80%;
}

.my_table_CL {
    border-collapse: collapse;
    min-width: 100%;
}
.my_table_CL td, .my_table_CL th {
    width: fit-content!important;
    border-top: 0!important;
    border-left: 0!important;
    border-right: 0!important;
    border-bottom: 1px solid var(--border-default)!important;
    padding: 5px 10px!important;
    text-align: left;
    vertical-align: middle;
}


.my_table_xy {
    border-collapse: collapse;
}
.my_table_xy tr >td {
    padding: 5px;
    text-align: center;
    border-left: 1px solid var(--border-strong);
    border-right: 1px solid var(--border-strong);
}
.my_table_xy tr >td:first-of-type {
    border-left: none;
}
.my_table_xy tr >td:last-of-type {
    border-right: none;
}
.my_table_xy tr:first-of-type >td {
    border-top: none;
    border-bottom: 1px solid var(--border-strong);
}
.my_table_xy tr:last-of-type >td {
    border-top: 1px solid var(--border-strong);
    border-bottom: none;
}


table td.no_border_td {
    border: none!important;
    text-align: center;
}
.my_table_left td, .my_table_left th{
    text-align: left;    
}
.table_centered {
    margin-left: auto;
    margin-right: auto;
}
table.cells_centered td, table.cells_centered th {
    text-align: center;
}
table.cells_right td, table.cells_right th {
    text-align: right;
}

.vertical_table td, .vertical_table th {
    border-left: 3px solid var(--border-default)!important;
    border-right: 3px solid var(--border-default)!important;
}
.vertical_table img {
    padding: 0 20px!important;
    max-width: 250px!important;
    min-width: 150px!important;
}
.narrow_table, .narrow_table tr {
    width: 1%!important;
}
.narrow_table td, .narrow_table th {
    width: 1%; 
    white-space: nowrap;
}


.table_input {
    text-align: center;
    width: 80px;
}
.table_input_30 {
    text-align: center;
    width: 30px;
    padding-left: 3px!important;
    padding-right: 3px!important;
}
.table_input_50 {
    text-align: center;
    width: 50px;
    padding-left: 3px!important;
    padding-right: 3px!important;
}
.success {
    color: var(--success);
    font-weight: bold;
    background-color: var(--surface-sunken);
    border-radius: 4px;
    display: block;
    margin: 5px 0;
    padding: 5px;
}
.failure {
    color: var(--danger);
    font-weight: bold;
    background-color: var(--surface-sunken);
    border-radius: 4px;
    display: block;
    margin: 5px 0;
    padding: 5px;
}
.ans_warning {
    color: var(--warning);
    font-weight: bold;
    background-color: var(--surface-sunken);
    border-radius: 4px;
    display: block;
    margin: 5px 0;
    padding: 5px;
}
.hidden {
    display: none!important;
}
.visible {
    display: block;
}
.coordinate {
    display: inline-block;
}
.ks_example {
    background-image: linear-gradient(to bottom, var(--colour-light-blue), transparent);
    border: 1px solid var(--colour-light-blue);
    border-radius: 5px;
    padding: 5px 8px;
    margin: 5px 0;
}
.question, .example, .question_like {
    color: var(--primary);
    font-weight: bold;
    font-size: large;
    padding: 5px 8px;
}
.question_text {
    color: var(--primary);
    background-color: var(--surface-sunken);
    font-style: italic;
    padding: 5px;
}
div[id^=question] {
    border: 1px solid;
    border-radius: 5px;
    border-image-source: linear-gradient(
        0deg,
        var(--border-default) 0%,
        transparent 80%
      );
    border-image-slice: 1;
    padding: 5px 8px;
    margin: 5px 3px;
}
.myequation {
    background-color: var(--colour-light-blue);
    border-radius: 5px;
    padding: 5px 8px;
}
.important {
    background-color: var(--surface-sunken);
    border: 2px solid var(--colour-blue-border);
    border-radius: 5px;
    padding: 5px 8px;
    margin: 3px 0;
}
span.show_next {
    display: inline-block;
}
.confirmTF, .confirm_choice, .confirm_multiple, 
.confirm_feedback_multiple, .show_solution, 
.show_next, .fill_show_next, .show_slides,
.any_button, .confirm_button_feedback,
.switch_confirm, .just_button {
    width: fit-content;
    color: var(--text-inverse);
    background-color: var(--colour-blue-border);
    text-align: center;
    padding: 5px 10px;
    margin: 5px 5px 5px 0;
    border-radius: 5px;
    border: 1px solid var(--colour-blue-border);
}

.confirmTF:hover, .confirm_choice:hover, .confirm_multiple:hover, .confirm_feedback_multiple:hover, 
.show_solution:hover, .show_next:hover, .fill_show_next:hover, .show_slides,.any_button:hover, 
.confirm_button_feedback,.switch_confirm:hover, .just_button:hover {
    cursor: pointer;
}

.switch_show_next {
    display: inline-block;
    width: fit-content;
    color: var(--text-inverse);
    background-color: var(--colour-blue-border);
    padding: 1px 3px;
    margin: 0 2px;
    border-radius: 5px;
    border: 1px solid var(--colour-blue-border);
}
.inline_button {
    display: inline-block;
    width: fit-content;
    color: var(--colour-blue-border);
    background-color: var(--surface-raised);
    text-align: center;
    padding: 5px 10px;
    margin: 5px 5px 5px 0;
    border-radius: 5px;
    border: 1px solid var(--colour-blue-border);
}
.inline_warning {
    display: inline-block;
    width: fit-content;
    color: var(--warning);
    background-color: var(--surface-raised);
    text-align: center;
    padding: 5px 10px;
    margin: 5px 5px 5px 0;
    border-radius: 5px;
    border: 1px solid var(--warning);
}
.inline_block {
    display: inline-block;
}
.ks_button:hover {
    cursor: pointer;
}
.ks_binary_choices {
    border-top: 1px solid var(--border-default);
}
.one_choice {
    display: inline-block;
    width: 150px;
    background-color: var(--surface-raised);
    color: var(--text-secondary);
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
    border: 1px solid var(--border-default);
}
.one_choice.on {
    background-color: var(--text-secondary);
    color: var(--text-inverse);
}
.one_choice_50 {
    width: 50px;
}
.truth, .false {
    display: inline-block;
    /* width: 50px; */
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
}
.truth {
    color: var(--success);
    border: 1px solid var(--success);
    background-color: var(--success-subtle);
}
.truth.chosen {
    color: var(--text-inverse);
    background-color: var(--success);
}
.false {
    color: var(--danger);
    border: 1px solid var(--danger);
    background-color: var(--danger-subtle);
}
.false.chosen {
    color: var(--text-inverse);
    background-color: var(--danger);
}
.correct_answer {
    border: 4px solid var(--success)!important;
    border-radius: 4px;
}
.wrong_answer {
    border: 4px solid var(--danger)!important;
    border-radius: 4px;
}
.no_answer {
    border: 1px solid var(--border-default);
    border-radius: 4px;
}
.white_grey_button, .white_gray_button {
    display: inline-block;
    width: 150px;
    background-color: var(--surface-raised);
    color: var(--text-secondary);
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
    border: 1px solid var(--border-default);
}
.white_grey_button.chosen, .white_gray_button.chosen {
    background-color: var(--text-secondary);
    color: var(--text-inverse);
}

.multi_many_ans, .multi_ans {
    display: inline-block;
    width: 150px;
    background-color: var(--surface-raised);
    color: var(--text-secondary);
    text-align: center;
    padding: 2px;
    margin: 2px;
    border-radius: 5px;
    border: 1px solid var(--border-default);   
}
.multi_many_ans.chosen, .multi_ans.chosen {
    background-color: var(--text-secondary);
    color: var(--text-inverse);
}
.multi_many_option {
    display: inline-block;
    background-color: var(--surface-raised);
    color: var(--text-secondary);
    text-align: center;
    padding: 2px;
    margin: 2px;
}
.mult_option {
    width: 50%;
    border: 1px solid var(--border-default);
    border-radius: 3px;
    padding: 3px;
    margin: 5px;
    background-color: none;
}
.mult_option.chosen {
    background-color: var(--surface-sunken);
}
.multiple_option {
    margin: 5px;
}
.multiple_option > div.inline {
    display: inline-block;
    vertical-align: middle;
}
.mult_feedback_incorrect {
    width: 50%;
    color: var(--danger);
    border: 1px solid var(--border-default);
    background-color: var(--surface-sunken);
    border-radius: 3px;
    padding: 3px;
    margin: 5px;
}
[id^="mult_choice"] {
    width: 1.5em;
    height: 1.5em;
}
.lightgreen {
    background-color: var(--colour-light-green);
}
.lightred {
    background-color: var(--colour-light-red);
}
/* tabs */
.ks_tabs {
    width: 90%;
    margin: auto;
}
.ks_tabs > div {
    padding: 15px;
    background-color: var(--surface-sunken);
    transition: opacity 200ms linear;
    display: none;
}
.ks_tabs > div.visible {
    display: block;
}
.ks_tabs > ul {
    text-align: center;
    list-style-type: none!important;
    display: flex;
    padding: 0!important;
    margin: 0!important;
}
.ks_tabs > ul > li {
    min-width: 30%;
    font-size: large;
    font-weight: bold;
    padding: 5px 5px 0 0;
    margin: 0!important;
}
.ks_tabs > ul > li > a {
    display: block;
    height: 2em;
    margin-right: 5px;
    padding-top: 5px;
    background-color: var(--surface-sunken);
    color: var(--text-primary);
    text-decoration: none;
    border-radius: 3px 3px 0 0;
    overflow: hidden;
    position: relative;
    bottom: 0;
}
.ks_tabs > ul > li > a.chosen {
    background-color: var(--surface-sunken);
    color: var(--primary);
}
.mark_done {
    border: none;
    padding: 5px;
    display: inline-block;
    width: fit-content;
    height: fit-content;
    background-color: var(--surface-raised);
    user-select: none;
}

.mark_done.on {
    background-color: var(--text-secondary);
}
ul:has(div.statement), .nolist {
    list-style-type: none!important;
}
.statement {
    display: inline-block;
    border-bottom: 1px solid var(--border-default);
    height: fit-content!important;
}

.question_solution, .question_answer {
    margin-top: 10px;
}
.replaced {
    border: 1px solid var(--success)!important;
    border-radius: 4px;
    text-align: center;
    display: inline-block;
    line-height: 2em;
}
/* slide show */
.arrows {
    display: block;
    height: 100px;
    width: 100%;
    position: relative;
}
.container_slide_title {
    position: absolute;
    left: 10%;
    width: 80%;
    display: flex;
    justify-content: center;
    align-items: center;
    margin-left: auto;
    margin-right: auto;
    height: 100px;
}
.slide_container {
    left: 10%;
    width: 80%;
    display: flex;
    justify-content: center;
    align-items: center;
    margin-left: auto;
    margin-right: auto;
    /* height: fit-content; */
}
.container_arrow {
    position: absolute;
    width: 10%;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 80px;
}
.container_arrow_left {
    left: 0;
}
.container_arrow_right {
    right: 0;
}
.slide_container > img {
    object-fit: cover;
}
.arrow_left {
    position: absolute;
    top: 0;
    left: 0;
    margin: auto;
}
.arrow_right {
    position: absolute;
    top: 0;
    right: 0;
    margin: auto;
}

.two_columns {
    width: 100%;
    margin: 0 auto;
}
.left_column {
    float: left;
    width: 49%;
}
.right_column {
    float: right;
    width: 49%;
}
.after_columns {
    content: none;
    display: table;
    clear: both;
}
.switch_line {
    padding: 5px 0;
    vertical-align: middle;
}
.switch_around {
    padding: 5px;
    display: inline-block;
    border: 2px none;
    height: 2em;
    width: fit-content;
}
.switch_value {
    padding: 5px;
    border-radius: 2px;
    cursor: pointer;
    border-width: 2px;
    border-style: solid;
    /* height: 2em!important; */
    height: fit-content!important;
    width: fit-content;
    margin-bottom: -0.7em;
}
.switch_value.progress {
    display: inline-block;
    border-color: var(--primary);
}
.switch_value.correct {
    border-color: var(--success);
}
details>summary {
    margin-bottom: 10px;
    cursor: pointer;
}
details>summary>h3, details>summary>h4 {
    display: inline-block;
}
sup {
    top: -1.5em!important;
}

blockquote {
    font-style: italic;
    padding-left: 20px;
    font-size: 110%;
}

.list15 li {
    margin-bottom: 1.5em;
}

.fbox {
    border: var(--border-default) 1pt solid;
    display: inline-block;
    padding: 3px;
}

ul.bold > li::marker, ol.bold > li::marker {
    font-weight: bold;
}

ul.bold > li, ol.bold > li {
    padding-left: 5px;
}

.border_red_thin {
    border: 1px solid var(--danger);
    padding: 5px;
}
.border_blue_thin {
    border: 1px solid var(--colour-blue-border);
    padding: 5px;
}
.red_on_yellow {
    color: red;
    background-color: yellow;
}
.blue_on_green {
    color: blue;
    background-color: rgb(130, 200, 130);
}

.magenta_on_gray {
    color: magenta;
    background-color: lightgray;
}
.yellow_on_gray {
    color: yellow;
    background-color: lightgray;
}

.rounded_corners {
    border-radius: var(--corner-radius);
}

.table_wrapper {
    overflow: auto;
}

.iframe_zonk {
    background-color: var(--primary-subtle);
    color: var(--danger);
    padding: 1rem;
}
.iframe_small {
    background-color: var(--surface-sunken);
    border: 2px solid var(--accent);
    border-radius: 1rem;
    padding: .5rem;
}
figure:has(embed) {
    position: relative; 
    width: 100%; 
    height: 0; 
    padding-bottom: 56.25%;
}
figure > embed {
    position: absolute; 
    width: 100%; 
    height:100%;
}
figure {
    text-align: center;
}
figure > img {
    max-width: 100%;
}
figure > figcaption {
    font-style: italic;
    font-size: smaller;
}
figure > video {
    max-width: 1000px;
}

.slidecontainer {
    width: 60%; /* Width of the outside container */
    margin:0 auto;
  }
/* The slider itself */
.slider {
    -webkit-appearance: none;  /* Override default CSS styles */
    appearance: none;
    width: 100%;
    height: 15px; /* Specified height */
    background: var(--border-strong); /* Grey background */
    outline: none; /* Remove outline */
    opacity: 0.7; /* Set transparency (for mouse-over effects on hover) */
    -webkit-transition: .2s; /* 0.2 seconds transition on hover */
    transition: opacity .2s;
}
/* Mouse-over effects */
.slider:hover {
    opacity: 1; /* Fully shown on mouse-over */
  }
  
  /* The slider handle (use -webkit- (Chrome, Opera, Safari, Edge) and -moz- (Firefox) to override default look) */
  .slider::-webkit-slider-thumb {
    -webkit-appearance: none; /* Override default look */
    appearance: none;
    width: 15px; /* Set a specific slider handle width */
    height: 15px; /* Slider handle height */
    background: var(--colour-light-blue); 
    cursor: pointer; /* Cursor on hover */
  }
  
  .slider::-moz-range-thumb {
    width: 15px; /* Set a specific slider handle width */
    height: 15px; /* Slider handle height */
    background: var(--colour-light-blue); 
    cursor: pointer; /* Cursor on hover */
  }


  .ks_tooltip {
    border: thin solid var(--border-default);
    border-radius: .2rem;
    padding: .2rem;
    text-decoration: underline;
  }

.clearfix::after {
    content: "";
    display: block;
    clear: both;
}"""


def _set(apps, css):
    Course = apps.get_model("courses", "Course")
    Course.objects.filter(slug="mat-pp").update(html_css=css)  # guarded: no-op if absent


def forward(apps, schema_editor):
    _set(apps, NEW_CSS)


def reverse(apps, schema_editor):
    _set(apps, OLD_CSS)


class Migration(migrations.Migration):
    dependencies = [("courses", "0030_iframeelement_dimensions")]
    operations = [migrations.RunPython(forward, reverse)]
