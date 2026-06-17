# libli — saved mockups

Accepted mockups from the brainstorming/design sessions, saved here for reference.
Each is a self-contained HTML file — open it directly in a browser. (Live exploration
happens in the visual companion under the gitignored `.superpowers/`; these are the
durable copies.)

| File | Screen / topic | Accepted decision |
|---|---|---|
| `identity-directions_V2-chosen.html` | Visual identity exploration (login screen, 3 button hues) | **V2 — warm teal** primary + amber accent, all-Inter, bold `libli.` dot. See [design-language.md](../design-language.md). |
| `app-shell-light-dark_accepted.html` | App shell + adaptive dashboard (light & dark) | Accepted — defines the reusable chrome (brand, nav, EN/PL switch, theme toggle, avatar) and dashboard sections. |
| `landing_accepted.html` | Public landing page (1.1) | Accepted — hero (log in + SSO + invite link) and an **"Open courses"** teaser. The open-courses section is **conditional: hidden entirely when there are no open courses.** |
| `auth-and-settings_accepted.html` | Signup/invite (1.4), password reset (1.5), SSO not-provisioned (1.3), 404 (1.7), ~~user settings (2.2)~~ | Accepted. Note: shown signup card is the *invite-accept* variant (email optional); the *open self-signup* form requires a **confirmed email** as bot defense. Username is read-only in settings (school-assigned). **The user-settings (2.2) card is superseded by `settings_redesign_accepted.html`** (WS4); the auth screens (1.3/1.4/1.5/1.7) here remain authoritative. |
| `settings_redesign_accepted.html` | User `/settings/` (2.2) + Platform-Admin `/settings/institution/` redesign (Phase 1b WS4) | Accepted — replaces the raw `{{ form.as_p }}` dropdowns with bonnot's friendly control vocabulary in libli's warm-teal identity + top-bar shell. Field→control: theme = SVG **tile previews**; language/default-language = **segmented**; enabled_languages = **toggle chips**; signup_policy = **radio cards**. Surfaces institution **name + logo** (new); brand **colours** stay Phase 5. User page adds editable **email** + a **Security** section (change-password, Google-SSO status). **No danger zone** (accounts are school-managed). Supersedes only the settings card of `auth-and-settings_accepted.html`; login (#15) stays on `identity-directions_V2-chosen.html`. |
| `dashboard-multirole_accepted-A.html` | Dashboard for multi-role users | **A** — one adaptive dashboard, collapsible + reorderable sections. |
| `notes-tags_accepted-Aplus.html` | Notes & tags placement | **A+** — in-context only (margin/mobile-modal notes, outline badges) + a "Manage tags" modal. No dedicated notes page in v1. |
| `analytics-matrix_accepted-option1.html` | Teacher analytics | **Option 1** — one configurable matrix (students × components × metric, drill-down, progress/results toggle). |
| `first-run-wizard_accepted-A.html` | First-run setup experience | **A** — guided wizard + persistent dashboard setup checklist. |
| `content-editor_accepted-A.html` | Unit content editor ｜ preview (Phase 1b-ii) | **A — balanced 50/50.** Editor pane (element cards: drag grip, type chip, summary, hover actions; inline-expanding edit form with live preview) ｜ sticky live-preview pane. "＋ Add element" reveals 5 type cards. Visual polish only — interaction model unchanged. In final warm-teal identity (light + dark). |
| `media-manager-and-picker_accepted.html` | Media manager page + editor picker modal (Phase 1b-ii) | Accepted. Manager: upload card (kind/file/**optional name**) + drag-drop, then a grid of asset cards showing a **readable display name** (bold) over the filename (muted), inline ✎ rename, usage badge + guarded delete; grid header has **search** (name + filename) and an **All/Images/Videos** type filter. Picker modal (editor-only): **kind-locked** to the element, Library/Upload tabs, search; Upload adds + auto-selects without leaving the editor. Adds a `MediaAsset` display-name field (migration) + a `?q=` search filter — beyond pure CSS. |

**Note on styling:** `identity-directions_V2-chosen` and `app-shell-light-dark_accepted` are
in libli's final **warm-teal identity**. The other four are earlier **wireframes** (neutral
styling) that captured *decisions*; they will be re-rendered in the real identity when their
phases (3 analytics, 4 notes/tags, 5 first-run) reach the mockup stage.
