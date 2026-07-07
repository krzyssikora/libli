# Integrations (grade sync)

libli can push finalized quiz results to your school information system
(SIS) or e-register via a signed webhook. Configure the endpoint under
**Manage → Settings → Integrations**.

## Setting it up

Enter the receiving **endpoint URL** and a **signing secret** shared with
your SIS integration. Once both are set, use **Send test event** to fire a
sample delivery at your receiver and confirm it accepts the request and
validates the signature before you rely on live grade delivery. A recent
deliveries list on the same tab shows the outcome of test and live
deliveries, including retries.

## What gets sent

Only courses with a **Register subject code** set (see
[Creating a course](create-a-course)) participate in grade sync; results
for a course without one never leave the platform. A delivery is queued
whenever a quiz submission is finalized for a synced course.

## The receiver contract

For the full payload shape, headers, HMAC signature verification, and the
retry/idempotency semantics your receiver must implement, see the dedicated
**[SIS webhook guide](/integrations/webhook/)** — the same guide your
integration developer can be pointed to directly, in either language.
