# First-run wizard

A brand-new installation opens into a guided **setup wizard** instead of the
plain home page, walking a Platform Admin through the handful of settings
worth deciding on day one.

![The first-run setup wizard](static:core/img/help/wizard.en.png)

## The steps

1. **Welcome** — an overview of what's ahead.
2. **Identity** — your institution's name, logo, colours and languages
   (the same fields as [Branding & settings](branding-settings)).
3. **Access** — sign-up policy and allowed email domains.
4. **Team** — send invitations to your first colleagues without leaving
   the wizard; see [Invitations](invitations) for what happens next.
5. **SSO** — optionally connect an OIDC identity provider; see
   [SSO (OIDC)](sso).

Identity, Access and SSO each have a **Skip** button that advances the
step without saving anything, so you can move straight to a working
platform and fill in the rest later — every one of these settings remains
editable from Settings afterwards. Team has no Skip button — its **Next**
button advances without sending any invitations.

## Revisiting or skipping entirely

**Skip setup for now** dismisses the wizard for the current session only;
it reappears next time until the flow is completed. Once finished, the
platform is marked as onboarded and the wizard does not reappear on its
own — the Identity step maps to the **Branding** tab, Access to the
**Access** tab and SSO to the **SSO** tab, each reachable from
**Admin → Institution settings**; Team has no settings-tab equivalent —
its invitations live at **Admin → People → Invitations** instead. You can
restart the guided flow anytime from **Admin → Setup wizard**.
