# AI First — Landing Site

A fast, static landing page for **AI First**: helping everyday people navigate AI for their life, job, and income.

## Files
- `index.html` — page markup and content
- `styles.css` — all styling (dark, modern, responsive)
- `script.js` — waitlist form handling + scroll reveals

No build step. No dependencies. Just open `index.html`.

## Run locally
Open the file directly, or serve it:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Deploy
Drop these three files on any static host:
- **GitHub Pages** — push to a repo, enable Pages on the branch
- **Netlify / Vercel / Cloudflare Pages** — drag-and-drop or connect the repo

## Connect the waitlist form
Right now the signup form stores emails in the browser (`localStorage`) as a
placeholder. To collect real signups, replace the `setTimeout` block in
`script.js` with a POST to your provider, e.g.:

- **Formspree**: `fetch("https://formspree.io/f/XXXX", { method: "POST", body: new FormData(form) })`
- **ConvertKit / Mailchimp / Beehiiv**: use their embed or API endpoint
- Your own backend `/api/waitlist`

## Customize
- Brand colors live in the `:root` block of `styles.css` (`--brand`, `--brand-2`, `--brand-3`).
- Copy is all in `index.html` — edit the hero, tracks, FAQ, and CTA freely.
