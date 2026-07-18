# Security Policy

Thanks for helping keep pagespeak and the people who use it safe.

## Reporting a vulnerability

**Please report security issues privately — do not open a public GitHub issue.**

Use GitHub's [private vulnerability reporting](https://github.com/phierceweb/pagespeak/security/advisories/new) (the **Security → Report a vulnerability** button on this repo). It opens a private channel between you and the maintainers.

Include enough to reproduce it: the affected version or commit, a minimal example (a sample document or request), and the impact you observed. We aim to acknowledge within a few business days, keep you updated on the fix, and credit you in the release notes unless you'd prefer to stay anonymous.

## Supported versions

pagespeak is pre-1.0 and ships from a single development line. Security fixes land on the **latest released version** (and `main`); there are no backports to older `0.x` tags. Pin to the newest tagged release to stay current.

## Security considerations when running pagespeak

pagespeak is a document-conversion library and CLI, not a multi-tenant service. A few things are worth knowing before you point it at untrusted input or expose the web console.

### The web console has no authentication

The optional web console (`pagespeak[web]` — `bin/start` in a checkout, or `uvicorn pagespeak.web:create_app --factory`) is a local operator tool. It binds to **`127.0.0.1` by default** (loopback only) and has **no login**. Anyone who can reach its port can upload and convert documents, trigger LLM calls (which cost money or quota on paid backends), and read converted output.

- **Do not bind it to a public interface.** Setting `PAGESPEAK_WEB_HOST=0.0.0.0` (or a LAN address) exposes it with no auth. If you need remote access, put it behind an authenticating reverse proxy or reach it over an SSH tunnel rather than exposing the port directly.
- **The rendered preview executes document content.** The console renders a converted document's markdown — including any raw HTML it contains and the Mermaid diagrams the vision model produced from its images — in your browser. Mermaid runs with `securityLevel: 'antiscript'` (scripts stripped), but raw HTML embedded in a hostile document can still execute in the preview. Treat opening a converted document's preview like opening the source itself: only render documents you trust, and keep the console on loopback.

### Converting untrusted documents

Conversion runs third-party parsers (Marker, Docling, MarkItDown, python-docx, pypdfium2) over the input file. A hostile document — a malformed PDF, a crafted zip/OOXML, or hostile HTML — is handled by those parsers, so the usual document-parsing risks apply: resource exhaustion (very large or zip-bomb inputs) and any parser-level bug in a dependency. Convert untrusted files with appropriate isolation (a sandbox or container, with resource limits) and keep the optional-backend dependencies up to date.

### Remote image fetching is SSRF-guarded (on by default)

HTML conversion downloads remote `<img>` URLs so the vision pass can see the figures (`PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=1`, the default). Because the source HTML may be untrusted, the downloader **refuses any URL that resolves to a private, loopback, link-local, reserved, multicast, or unspecified address, fails closed on hosts it cannot resolve, and re-checks every redirect hop** — so a malicious document cannot steer it at `localhost`, your private network, or a cloud metadata endpoint (e.g. `169.254.169.254`). Set `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0` to disable remote fetching entirely.

### API keys and secrets

API keys (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`) are read from the environment or a local `.env` (which is gitignored) — never hardcode them or commit `.env`. The optional LLM-tracking database stores call metadata (tokens, cost, model name), not your keys.
