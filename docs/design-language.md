# libli — Design Language

*Decided 2026-06-13 via mockup exploration. libli uses a **bespoke, token-driven**
design system (no CSS framework), seeded from the sibling app **bonnot**'s token
architecture but with libli's own values. See the [Phase 0 spec](superpowers/specs/2026-06-13-phase-0-foundations-design.md) §6.*

## Identity (chosen direction: "warm teal", V2)

- **Feel:** warm, calm, credible — academic but friendly, not corporate-cold and not childish.
- **Surfaces:** warm off-white / cream (not cold pure-white).
- **Primary:** warm **teal**. **Accent:** **amber** — used for the brand dot and links.
- **Typography:** all-**Inter** (UI + headings); friendly, crisp. (Optional serif/mono can
  be added later for content rendering in Phase 1.)
- **Brand mark:** the wordmark **`libli`** followed by a bold amber **dot** (`libli.`) — a
  deliberate, visible accent.
- **Shape:** medium-soft radii (cards ~12px, controls ~7px).
- **Per-institution branding** overrides `--primary` and `--accent` (and logo); the structural
  identity (type, spacing, radii, component feel) stays constant across institutions.

## Tokens — light mode (`:root`)

```css
:root {
  /* surfaces */
  --surface-base:   #F4F1EA;   /* app background */
  --surface-raised: #FFFFFF;   /* cards, modals */
  --surface-sunken: #FAF8F3;   /* inputs */
  --surface-overlay: rgba(30,28,24,0.45);
  /* text */
  --text-primary:   #1E1C18;
  --text-secondary: #5A544A;
  --text-tertiary:  #8A8477;
  --text-inverse:   #FBF9F4;
  /* borders */
  --border-subtle:  #EDE8DE;
  --border-default: #E7E1D6;
  --border-strong:  #D6CFC1;
  /* brand / accent  (institution-overridable) */
  --primary:        #147E78;   /* warm teal */
  --primary-hover:  #0F6A65;
  --primary-active: #0B5651;
  --primary-subtle: #DCEDEB;
  --accent:         #C77B2A;   /* amber: the dot + links */
  --accent-hover:   #AC6A22;
  --accent-subtle:  #F4E6D2;
  /* semantic */
  --success: #5A7D3C; --success-subtle: #E3ECD7;
  --warning: #B8811F; --warning-subtle: #F4E8CD;
  --danger:  #A8392E; --danger-subtle:  #F2D9D5;
  /* radius */
  --radius-sm: 7px; --radius-md: 10px; --radius-lg: 12px; --radius-xl: 18px; --radius-full: 9999px;
  /* shadow (warm-tinted) */
  --shadow-xs: 0 1px 2px rgba(30,28,24,.06);
  --shadow-sm: 0 2px 6px rgba(30,28,24,.08);
  --shadow-md: 0 6px 16px rgba(30,28,24,.10);
  --shadow-lg: 0 16px 40px rgba(30,28,24,.14);
  /* typography */
  --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --heading-letter-spacing: -0.015em;
  /* spacing: reuse bonnot's 4px grid (--space-1..10) and motion tokens */
}
```

## Tokens — dark mode (`[data-theme="dark"]`)

```css
[data-theme="dark"] {
  --surface-base:   #1A1816;
  --surface-raised: #2C2925;
  --surface-sunken: #15130F;
  --surface-overlay: rgba(0,0,0,0.55);
  --text-primary:   #F2EFE9;
  --text-secondary: #BDB6A8;
  --text-tertiary:  #8A8477;
  --text-inverse:   #1E1C18;
  --border-subtle:  #2A2620;
  --border-default: #322E29;
  --border-strong:  #4A4036;
  --primary:        #4FB3AC;   /* teal lifted for contrast */
  --primary-hover:  #63C2BB;
  --primary-active: #7ACFC8;
  --primary-subtle: #1B3A38;
  --accent:         #E5A159;   /* amber lifted */
  --accent-hover:   #EFB070;
  --accent-subtle:  #3D2E1A;
  --success: #9FBF7B; --success-subtle: #2A3620;
  --warning: #E8B761; --warning-subtle: #3A2F18;
  --danger:  #E57373; --danger-subtle:  #3A1E1A;
  --shadow-xs: 0 1px 2px rgba(0,0,0,.4);
  --shadow-sm: 0 2px 6px rgba(0,0,0,.45);
  --shadow-md: 0 6px 16px rgba(0,0,0,.5);
  --shadow-lg: 0 16px 40px rgba(0,0,0,.55);
}
```

## Notes for implementation (Phase 0)

- Theme via `data-theme` on `<html>`; per-user `light`/`dark`/`auto` (auto → `prefers-color-scheme`);
  pre-paint inline script to avoid flash.
- Reuse bonnot's spacing (4px grid), motion (durations/easings), base reset, focus-ring, and
  primitive component CSS as starting points; restyle to these tokens.
- Verify WCAG AA contrast for text/controls in both themes (bonnot documents this practice).
- Self-host **Inter** (don't depend on Google Fonts in production).
