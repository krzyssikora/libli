# Integrations (grade sync)

libli can push finalized quiz results to your school information system
(SIS) or e-register via a signed webhook. Configure the endpoint under
**Admin → Institution settings → Integrations**.

![The integrations settings tab](static:core/img/help/integrations.en.png)

## Setting it up

Live grade sync needs **four things**: an **Endpoint URL**, a **Signing
secret** shared with your SIS integration, **Enable result sync** ticked
and saved, and a course with a **Register subject code** set (see
[Creating a course](create-a-course)).

Once the endpoint URL and signing secret are saved, **Send test event**
fires a sample delivery at your receiver so you can confirm it accepts the
request and validates the signature. This test only checks that a URL and
secret are saved — it does **not** check whether **Enable result sync** is
ticked, so a passing test proves your receiver works but proves nothing
about whether live grade sync is actually switched on. Tick **Enable
result sync** yourself before relying on live delivery. A recent
deliveries list on the same tab shows the outcome of test and live
deliveries, including retries.

## What gets sent

Only courses with a **Register subject code** set participate in grade
sync; results for a course without one never leave the platform. When a
quiz submission is finalized for a synced course, one delivery is queued
per group the student belongs to — or exactly one delivery if the student
belongs to no group, never zero. If the submission has questions awaiting
manual review, no delivery is queued at submit time; one is queued once
the review is completed and the result becomes final.

## The receiver contract

For the full payload shape, headers, HMAC signature verification, and the
retry/idempotency semantics your receiver must implement, see the dedicated
**[SIS webhook guide](/integrations/webhook/)** — the same guide your
integration developer can be pointed to directly, in either language.
