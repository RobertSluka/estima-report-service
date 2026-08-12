# Spec: make the estimacz.cz contact form deliver mail

> **Status 2026-08-12: Part 1 (honeypot) and Part 3 (.env.example) APPLIED** in
> `estima-frontend/byteval` commit `0857a32` (on local `main`, **not pushed**).
> **Part 2 — supplying `RESEND_API_KEY` on the VPS — is still open and is the
> blocker: until it is done, estimacz.cz still answers 503 and delivers no
> mail.** Verified by typecheck, `next build`, and driving the built app at
> 127.0.0.1:3015 with a deliberately invalid dummy key.

**Handover doc** for `estima-frontend/byteval`.
Companion to [`estima-sk-contact-form-honeypot-fix.md`](estima-sk-contact-form-honeypot-fix.md).
Diagnosed 2026-08-12. Goal: /contact on estimacz.cz delivers to
`estimafirm@gmail.com`, the way estima.sk's send path already does.

CZ needs **two** things, and the order matters. The key alone would ship the
same silent-drop bug SK has.

## Current state

| Check | SK | CZ |
|---|---|---|
| `POST /api/contact` with `{}` | `400 bad_request` | **`503 not_configured`** |
| `RESEND_API_KEY` present at runtime | yes | **no** |
| Honeypot bug (`if (body.website)`) | present | **present** |
| Recipient default (`CONTACT_EMAIL_TO`) | `estimafirm@gmail.com` | `estimafirm@gmail.com` |
| Subject line | `Správa z estima.sk — {name}` | `Zpráva z Estimy (CZ) — {name}` |

`app/api/contact/route.ts` and `app/contact/page.tsx` in byteval are a
straight port of the SK pair — same `KEY()/TO()/FROM()` helpers, same
throttle, same `website` honeypot, same mailto fallback. The only deltas are
the subject string and an es5-safe `hits.forEach` sweep.

Because CZ returns 503, **every CZ contact submission since launch has gone
down the mailto fallback path** — the visitor got the green
"we opened a draft" panel and the message only arrived if their browser had a
mail handler and they actually hit send.

## Part 1 — apply the honeypot fix first

`app/contact/page.tsx:220` has the identical live text input named `website`
with `className="sr-only"`, and `route.ts:72` has the identical
`if (body.website) return NextResponse.json({ ok: true })`.

Apply sections 1–4 of the SK spec verbatim to the CZ files (rename to
`hp_ref_token` in both files, move the input out of the layout, log the trip,
turn the non-OK branch into a real error state). Paths differ:

| SK | CZ |
|---|---|
| `app/kontakt/page.tsx` | `app/contact/page.tsx` |
| `app/api/contact/route.ts` | `app/api/contact/route.ts` |

Do this **before** Part 2. Enabling the key on top of the unfixed honeypot
just converts CZ's current visible-but-useless mailto fallback into an
invisible failure, which is strictly worse for diagnosis.

## Part 2 — supply the key on the VPS

The built CZ bundle keeps `process.env.RESEND_API_KEY||""` as a **runtime**
read (verified in `.next/server/app/api/contact/route.js`), so the key does
not need a rebuild — only a container recreate with the env set.

Do not copy SK's mechanism. On SK the secret reaches the image through a
gitignored env file picked up by `COPY . .`; CZ's `.dockerignore` **excludes
`.env.local`**, so that approach silently produces a container with no key —
very likely why CZ is unconfigured today. Baking a secret into an image is
also the wrong default. Pass it at runtime instead.

CZ has no `docker-compose.yml` in the repo (SK does) — the Dockerfile comment
says the port is overridden at `docker run` (3002 on the VPS; 3000 there
belongs to SK). So first recover how the running container was started:

```bash
docker inspect estima-cz-frontend --format '{{json .Config.Cmd}} {{json .Config.Env}} {{.HostConfig.NetworkMode}}'
```

Then recreate it with the same command plus the contact env. Three vars, only
the first is required:

| Var | Value |
|---|---|
| `RESEND_API_KEY` | the current `re_…` secret (same Resend account as SK) |
| `CONTACT_EMAIL_TO` | omit — the `estimafirm@gmail.com` default is correct |
| `CONTACT_EMAIL_FROM` | omit unless a domain is verified (see below) |

**This step is yours to run.** SSH to the VPS is blocked for the agent by the
permission classifier, and handling API keys is off-limits regardless — the
key must never be pasted into a chat or a tracked file.

### Sender caveat

`FROM()` defaults to Resend's shared `onboarding@resend.dev`, which only
delivers to the Resend account owner's own address. That is fine here because
`CONTACT_EMAIL_TO` is `estimafirm@gmail.com`, the account owner — it is why SK
works today. If CZ should ever notify a different inbox, verify a domain in
Resend (estimacz.cz) and set `CONTACT_EMAIL_FROM` to a sender on it. Until
then, leave both defaults alone.

## Part 3 — document the vars

`byteval/.env.example` documents `ADMIN_*`, `INTERNAL_API_KEY`, `GOOGLE_*` and
`STRIPE_*` but says nothing about the contact form. Add a section for
`RESEND_API_KEY` / `CONTACT_EMAIL_TO` / `CONTACT_EMAIL_FROM` matching the
style of the existing blocks, noting that the endpoint is disabled (503) while
the key is unset. Same omission exists in `estima-sk/.env.example` — worth
fixing in both.

## Verification

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://estimacz.cz/api/contact \
  -H 'Content-Type: application/json' -d '{}'
```

- [ ] Returns **400**, not 503 (the `!KEY()` guard now passes)
- [ ] A real submission from the CZ form lands in `estimafirm@gmail.com` with
      subject `Zpráva z Estimy (CZ) — …` and reply-to set to the visitor
- [ ] The Resend dashboard shows the row (CZ and SK are distinguishable by
      subject prefix)
- [ ] `curl` with `"hp_ref_token":"x"` returns 200 and sends nothing
- [ ] Submitting from a browser with a saved address/identity profile still
      produces a Resend row — this is the regression the honeypot fix targets;
      a clean profile will not catch it
- [ ] A forced failure renders an error state, not a green success panel
