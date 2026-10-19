import type { BrandContext } from "../services/brand.js";

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderLandingPage(brand: BrandContext): string {
  const brandName = escapeHtml(brand.brand_name);
  const tagline = escapeHtml(brand.tagline);
  const website = escapeHtml(brand.website ?? "https://getconverza.com");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${brandName} — ${tagline}</title>
  <meta name="description" content="Hire a 19-agent AI team that creates video ads and closes inbound DMs 24/7.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #F9F8F6;
      --surface: #ffffff;
      --border: #E5E3DA;
      --text: #1C1B19;
      --muted: #57534e;
      --accent: #1b5bf7;
      --accent-soft: #dbe6ff;
      --lead: #16a34a;
      --support: #ca8a04;
      --spam: #dc2626;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: Inter, system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
      color-scheme: light;
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(to right, rgba(68, 64, 60, 0.045) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(68, 64, 60, 0.045) 1px, transparent 1px);
      background-size: 72px 72px;
      mask-image: radial-gradient(ellipse at center, black 0%, black 60%, transparent 100%);
      -webkit-mask-image: radial-gradient(ellipse at center, black 0%, black 60%, transparent 100%);
    }

    .wrap {
      position: relative;
      max-width: 640px;
      margin: 0 auto;
      padding: 2.5rem 1.25rem;
      overflow-x: hidden;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 2rem;
      gap: 1rem;
    }

    .brand-link {
      color: inherit;
      text-decoration: none;
    }

    h1 {
      font-family: Georgia, Cambria, "Times New Roman", serif;
      font-size: 1.5rem;
      font-weight: 400;
      letter-spacing: -0.035em;
    }

    .tagline {
      font-size: 0.8rem;
      color: var(--muted);
      margin-top: 0.15rem;
    }

    nav {
      display: flex;
      gap: 1rem;
      font-size: 0.875rem;
    }

    nav a {
      color: var(--muted);
      text-decoration: none;
    }

    nav a:hover { color: var(--accent); }

    .panel {
      display: grid;
      gap: 0.75rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
      min-width: 0;
      overflow: hidden;
    }

    textarea {
      width: 100%;
      min-height: 5.5rem;
      resize: vertical;
      font: inherit;
      font-size: 0.95rem;
      color: var(--text);
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
      outline: none;
    }

    textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    button {
      font: inherit;
      font-weight: 500;
      font-size: 0.9rem;
      color: #fff;
      background: var(--accent);
      border: none;
      border-radius: 8px;
      padding: 0.6rem 1rem;
      cursor: pointer;
      justify-self: start;
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    #result {
      min-height: 1.5rem;
      min-width: 0;
      max-width: 100%;
      font-size: 0.95rem;
      overflow: hidden;
    }

    .badge {
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      margin-bottom: 0.75rem;
    }

    .badge.intent-LEAD_HOT { background: #dcfce7; color: var(--lead); }
    .badge.intent-SUPPORT_REQUEST { background: #fef9c3; color: var(--support); }
    .badge.intent-SPAM_OR_TRASH { background: #fee2e2; color: var(--spam); }

    .reply {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
      max-width: 100%;
    }

    .reply.muted {
      color: var(--muted);
      font-style: italic;
    }

    .checkout-link {
      display: inline-block;
      margin-top: 0.5rem;
      font-size: 0.875rem;
      color: var(--accent);
      word-break: break-all;
    }

    .error {
      color: var(--spam);
      font-size: 0.9rem;
    }

    .json-panel {
      margin-top: 0.75rem;
      max-width: 100%;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      background: #f3f4f6;
    }

    .json-toggle {
      display: flex;
      align-items: center;
      gap: 0.45rem;
      width: 100%;
      padding: 0.55rem 0.75rem;
      font: inherit;
      font-size: 0.8rem;
      font-weight: 600;
      color: #374151;
      background: #e5e7eb;
      border: none;
      cursor: pointer;
      text-align: left;
    }

    .json-toggle:hover {
      background: #d1d5db;
    }

    .json-toggle-icon {
      display: inline-block;
      font-size: 0.7rem;
      color: #6b7280;
      transition: transform 0.15s ease;
    }

    .json-file-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2rem;
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      color: #854d0e;
      background: #fef08a;
      border: 1px solid #fde047;
    }

    .json-block {
      display: none;
      margin: 0;
      max-width: 100%;
      box-sizing: border-box;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.75rem;
      line-height: 1.5;
      color: #374151;
      background: #ffffff;
      border-top: 1px solid var(--border);
      padding: 0.85rem;
      overflow-x: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .json-panel.open .json-block {
      display: block;
    }

    .json-panel.open .json-toggle-icon {
      transform: rotate(90deg);
    }

    .json-key { color: #1b5bf7; }
    .json-string { color: #15803d; }
    .json-number { color: #c2410c; }
    .json-literal { color: #7c3aed; }
    .json-punct { color: #6b7280; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <a class="brand-link" href="${website}" target="_blank" rel="noopener">
        <h1>${brandName}</h1>
        <p class="tagline">${tagline}</p>
      </a>
      <nav>
        <a href="/docs">API</a>
        <a href="${website}" target="_blank" rel="noopener">getconverza.com</a>
      </nav>
    </header>

    <div class="panel">
      <textarea id="message" placeholder="Message" aria-label="Message"></textarea>
      <button type="button" id="send">Send</button>
      <div id="result"></div>
    </div>
  </div>

  <script>
    const messageEl = document.getElementById("message");
    const resultEl = document.getElementById("result");
    const sendBtn = document.getElementById("send");

    const intentLabels = {
      LEAD_HOT: "Lead",
      SUPPORT_REQUEST: "Support",
      SPAM_OR_TRASH: "Spam",
    };

    function escapeHtml(str) {
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function highlightJson(data) {
      const raw = JSON.stringify(data, null, 2);
      let html = escapeHtml(raw);

      html = html.replace(
        /(&quot;(?:\\.|[^&])*?&quot;)(\s*:)/g,
        '<span class="json-key">$1</span><span class="json-punct">$2</span>',
      );
      html = html.replace(
        /(:\s*)(&quot;(?:\\.|[^&])*?&quot;)/g,
        '$1<span class="json-string">$2</span>',
      );
      html = html.replace(
        /(:\s*)(-?\d+\.?\d*(?:e[+-]?\d+)?)/gi,
        '$1<span class="json-number">$2</span>',
      );
      html = html.replace(
        /(:\s*)(true|false|null)\b/g,
        '$1<span class="json-literal">$2</span>',
      );

      return html;
    }

    function renderJsonPanel(data) {
      return (
        '<div class="json-panel">' +
          '<button type="button" class="json-toggle" aria-expanded="false">' +
            '<span class="json-toggle-icon">▸</span>' +
            '<span class="json-file-icon">JSON</span>' +
            '<span>Response</span>' +
          "</button>" +
          '<pre class="json-block">' + highlightJson(data) + "</pre>" +
        "</div>"
      );
    }

    function renderResult(data) {
      const intentClass = "intent-" + data.intent;
      const intentLabel = intentLabels[data.intent] || data.intent;

      let replyHtml = "";
      if (data.reply) {
        replyHtml = '<div class="reply">' + escapeHtml(data.reply) + "</div>";
        if (data.checkout_link) {
          replyHtml += '<a class="checkout-link" href="' + escapeHtml(data.checkout_link) + '" target="_blank" rel="noopener">' + escapeHtml(data.checkout_link) + "</a>";
        }
      } else {
        replyHtml = '<div class="reply muted">—</div>';
      }

      resultEl.innerHTML =
        '<span class="badge ' + intentClass + '">' + escapeHtml(intentLabel) + "</span>" +
        replyHtml +
        renderJsonPanel(data);
    }

    async function qualify() {
      const message = messageEl.value.trim();
      if (!message) {
        messageEl.focus();
        return;
      }

      sendBtn.disabled = true;
      resultEl.textContent = "…";

      try {
        const res = await fetch("/v1/qualify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message }),
        });
        const data = await res.json();
        if (!res.ok) {
          resultEl.innerHTML =
            '<p class="error">' + escapeHtml(data.message || data.error || "Request failed") + "</p>" +
            renderJsonPanel(data);
          return;
        }
        renderResult(data);
      } catch (err) {
        resultEl.innerHTML = '<p class="error">' + escapeHtml(String(err)) + "</p>";
      } finally {
        sendBtn.disabled = false;
      }
    }

    resultEl.addEventListener("click", (e) => {
      const toggle = e.target.closest(".json-toggle");
      if (!toggle) return;
      const panel = toggle.closest(".json-panel");
      if (!panel) return;
      const open = panel.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    sendBtn.addEventListener("click", qualify);
    messageEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        qualify();
      }
    });
  </script>
</body>
</html>`;
}
