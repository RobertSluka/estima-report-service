# Spec: estima.sk contact form silently drops messages (honeypot false positive)

> **Status 2026-08-12: APPLIED** in `estima-sk` commit `ce092b3` (on local
> `main`, **not pushed**). Verified by typecheck, `next build`, and driving the
> built app at 127.0.0.1:3013. Deploy still pending — see Deployment below.
> Kept for the rationale and the verification checklist.

**Handover doc** for `estima-sk`. Diagnosed
2026-08-12 from estima-report-service. Goal: the /kontakt form actually
delivers to `estimafirm@gmail.com`, and a real failure stops looking like
success.

**Severity: high, and silent.** Live since the form shipped (`9741142`,
2026-07-30). Affected submissions produce no error, no Resend row, and no
record anywhere — there is no way to recover the lost leads or count them.

## Symptom

Visitor fills the form, sees the green `"Vaša správa bola odoslaná"` panel,
no e-mail arrives, and nothing appears in the Resend dashboard (not even a
failed row).

## Evidence

Probes against the live endpoint, 2026-08-12:

| Request to `https://estima.sk/api/contact` | Status | Resend row |
|---|---|---|
| `{}` | `400 bad_request` | — (proves `RESEND_API_KEY` is set: the `!KEY()` guard returns 503 before validation) |
| valid body **+** `"website":"http://example.com"` | `200 {"ok":true}` | **none** |
| valid body, no `website` | `200 {"ok":true}` | delivered |
| `https://estimacz.cz/api/contact` `{}` | `503 not_configured` | — (CZ has no key at all) |

So the key is valid, the route works, and the container env is correct. The
green panel the user saw is the `sentViaApi` branch, which only renders on a
**200** — so the request succeeded *and* sent nothing. Exactly one path in the
route does that.

## Root cause

`app/api/contact/route.ts`:

```ts
// Honeypot tripped — report success so bots learn nothing.
if (body.website) return NextResponse.json({ ok: true })
```

`app/kontakt/page.tsx:218` renders that honeypot as a genuine text input:

```tsx
<input
  type="text"
  name="website"
  value={website}
  onChange={(e) => setWebsite(e.target.value)}
  tabIndex={-1}
  autoComplete="off"
  aria-hidden="true"
  className="sr-only"
/>
```

`sr-only` clips it visually but leaves it in the layout as a live field named
`website`. Chrome/Brave autofill and password managers classify `website` /
`url` as an identity field and fill it — and they routinely ignore
`autocomplete="off"`. Any visitor with an address/identity profile saved trips
the honeypot and gets a fake success.

## Fix

### 1. Rename the honeypot (the actual fix)

Autofill matches on `name`/`id`/label semantics, so the field must not look
like anything a profile has a value for. Rename in **both** files — they are
one contract:

- `page.tsx`: `const [website, setWebsite]` → `const [hpToken, setHpToken]`;
  input `name="website"` → `name="hp_ref_token"`; request body
  `{ ...form, website }` → `{ ...form, hp_ref_token: hpToken }`.
- `route.ts`: `ContactBody.website?: string` → `hp_ref_token?: string`; the
  guard becomes `if (body.hp_ref_token)`.

Do not leave a `website` alias on the server for compatibility — that would
keep the exact failure alive.

### 2. Take it out of the layout

`sr-only` is for content screen readers *should* reach. Replace with:

```tsx
style={{ position: "absolute", left: "-9999px", width: 0, height: 0, overflow: "hidden" }}
```

Keep `tabIndex={-1}` and `aria-hidden="true"`; drop `className="sr-only"`.

### 3. Make a trip visible

Returning a bare `ok: true` is why this ran unnoticed for two weeks. Before
the early return, `console.warn` the trip with the IP and the field value.
Container logs then show whether it is firing on real people again.

### 4. Fix the failure UX (separate bug, same file)

`handleSubmit` sends every non-OK response to `openDraft()`, which renders the
same **green** panel with `"Otvorili sme koncept e-mailu"`. If the browser has
no `mailto:` handler (common — webmail users), the message is lost behind a
success screen. Make the non-OK path a visible error state: red/amber, plain
statement that sending failed, the address `estimafirm@gmail.com` shown
inline as selectable text, and the mailto link offered as an action rather
than presented as something that already happened.

Note this bug did **not** cause the reported symptom (that was a 200), but it
is why any real outage would also go unnoticed.

## Also worth doing (not part of the fix)

`estimacz.cz/api/contact` returns `503 not_configured` — CZ has no
`RESEND_API_KEY`, so every CZ contact submission since launch has gone down
the mailto fallback path. Either set the key on the CZ container or make the
CZ form honest about being mailto-only.

## Deployment

`RESEND_API_KEY` is not in any tracked file — `.env.production` holds only
`NEXT_PUBLIC_API_URL`, and `docker-compose.yml` declares no `environment:` or
`env_file:`. On the VPS it reaches the container through a server-local env
file picked up by `COPY . .`, i.e. **at image build time**. Any change to it
needs a rebuild, not a restart:

```bash
cd ~/server/estima-sk && git pull && docker compose up -d --build
```

Never pass `--remove-orphans` (shared compose project name).

## Acceptance criteria

- [ ] Submitting /kontakt from a browser with a saved address/identity profile
      produces a Resend row (this is the regression case — test it in Brave or
      Chrome with autofill on, not just a clean profile)
- [ ] `curl` with `"hp_ref_token":"x"` still returns 200 and sends nothing
- [ ] No field named `website` or `url` remains in the form markup
- [ ] A forced failure (temporarily invalid key) renders an error state, not a
      green success panel, and shows the address inline
- [ ] Container logs show a warning line when the honeypot trips
