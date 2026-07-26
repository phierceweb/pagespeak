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

HTML conversion downloads remote `<img>` URLs so the vision pass can see the figures (`PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=1`, the default). Because the source HTML may be untrusted, the fetch runs through pf-core's guarded fetch core (`pf_core.fetch`), which **accepts only `http`/`https` URLs, refuses any URL that resolves to a private, loopback, link-local, reserved, multicast, or unspecified address, fails closed on hosts it cannot resolve, and re-checks every redirect hop** — so a document cannot simply name `localhost`, a private-network host, or a cloud metadata endpoint (e.g. `169.254.169.254`) and have it fetched. Each response is also size-capped (`PAGESPEAK_REMOTE_IMAGE_MAX_BYTES`): an oversized figure is abandoned mid-read and its ref left remote.

**The check is not DNS-rebinding-proof.** It validates the addresses a host resolves to *at check time*; the HTTP client resolves the host again when it connects, and pagespeak does not pin the connection to the vetted addresses. A hostile host with a short-TTL record that alternates between a public and an internal address can therefore still be reached. Convert untrusted HTML with network isolation, or set `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0`.

- Set `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0` to disable remote fetching entirely.
- The address check has a deliberate opt-out: pf-core's `URL_FETCH_ALLOW_PRIVATE=1` allows non-public targets (for operators who intentionally fetch internal hosts). Do not set it while converting untrusted documents — the scheme check still applies, but nothing else does.

### API keys and secrets

API keys (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`) are read from the environment or a local `.env` (which is gitignored) — never hardcode them or commit `.env`. Keys are never written to the tracking database.

### The LLM-tracking database stores document text

The tracking database records more than call metadata. Alongside tokens, cost, model name, and duration, it stores **the rendered prompt and the raw model response for every LLM call** — and those prompts carry document content. Heading normalization sends each heading together with up to 800 characters of its own body text; the vision pass stores the model's description of each figure. Converting a confidential document therefore leaves excerpts of that document in the database.

It is **on by default for the CLI**, writing to `~/.pagespeak/llm_tracking.db` (or wherever `DATABASE_URL` points). For library consumers it is off unless the process calls `pagespeak._db.init_db()`.

- The database outlives the conversion and is **not** stripped by `pagespeak deliver`.
- The web console re-serves its contents at `/admin/llm`.
- Pointing `DATABASE_URL` at a shared Postgres or MySQL shares those excerpts with everyone who can read that database.

If you convert sensitive material with the CLI, treat `llm_tracking.db` as containing that material: keep it on encrypted local storage, or point `DATABASE_URL` at a database you control and prune it.
