# paperhound — landing page

Static, framework-free landing page for [paperhound](https://github.com/alexfdez1010/paperhound).
Single `index.html` + embedded CSS/JS, served from this folder via GitHub Pages.

## Local preview

```bash
# any static server works
python -m http.server -d web 8000
# → http://localhost:8000
```

## Deploy

Auto-deployed by `.github/workflows/pages.yml` on every push to `main`
that touches `web/**`. Enable Pages once in repo settings:

> **Settings → Pages → Build and deployment → Source: GitHub Actions**

Then push. The workflow uploads `web/` as a Pages artifact and publishes
it. `.nojekyll` disables Jekyll so files starting with `_` are served as-is.

## Stack

- HTML + CSS + ~30 LOC of JS (clipboard + scroll reveal)
- Fonts: Fraunces (display) + JetBrains Mono (mono), via Google Fonts
- No build step. No framework. No package manager.
