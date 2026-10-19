/** Swagger UI — styled to match https://getconverza.com */
export function renderDocsPage(): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Converza — API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    html { box-sizing: border-box; overflow-y: scroll; color-scheme: light; }
    *, *::before, *::after { box-sizing: inherit; }
    body {
      margin: 0;
      background: #F9F8F6;
      color: #1C1B19;
      font-family: Inter, system-ui, sans-serif;
    }
    .topbar { display: none; }
    .swagger-ui .info .title {
      font-family: Georgia, Cambria, serif;
      font-weight: 400;
      letter-spacing: -0.035em;
      color: #1C1B19;
    }
    .swagger-ui .info a { color: #1b5bf7; }
    .swagger-ui .btn.authorize,
    .swagger-ui .btn.execute {
      background: #1b5bf7;
      border-color: #1b5bf7;
    }
    .site-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1rem 1.25rem;
      border-bottom: 1px solid #E5E3DA;
      background: #F9F8F6;
    }
    .site-bar a {
      color: #57534e;
      text-decoration: none;
      font-size: 0.875rem;
    }
    .site-bar a:hover { color: #1b5bf7; }
    .site-bar .brand {
      font-family: Georgia, Cambria, serif;
      color: #1C1B19;
      font-size: 1rem;
      letter-spacing: -0.035em;
    }
  </style>
</head>
<body>
  <div class="site-bar">
    <span class="brand">Converza — API</span>
    <div>
      <a href="/">App</a>
      &nbsp;·&nbsp;
      <a href="https://getconverza.com" target="_blank" rel="noopener">getconverza.com</a>
    </div>
  </div>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis],
      layout: "BaseLayout",
    });
  </script>
</body>
</html>`;
}
