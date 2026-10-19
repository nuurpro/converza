import "dotenv/config";
import express from "express";
import { openApiSpec } from "./openapi.js";
import { loadBrandContext } from "./services/brand.js";
import { qualifyRouter } from "./routes/qualify.js";
import { renderDocsPage } from "./ui/docs.js";
import { renderLandingPage } from "./ui/landing.js";

const PORT = Number(process.env.PORT ?? 3000);

// Fail fast if brand context is missing/invalid
loadBrandContext();

const app = express();
app.use(express.json({ limit: "32kb" }));

app.get("/", (_req, res) => {
  const brand = loadBrandContext();
  res.type("html").send(renderLandingPage(brand));
});

app.get("/health", (_req, res) => {
  const brand = loadBrandContext();
  res.json({ ok: true, service: "converza", brand: brand.brand_name });
});

app.get("/docs", (_req, res) => {
  res.type("html").send(renderDocsPage());
});

app.get("/openapi.json", (_req, res) => {
  res.json(openApiSpec);
});

app.use("/v1", qualifyRouter);

app.listen(PORT, () => {
  console.log(`Converza listening on http://localhost:${PORT}`);
  console.log(`POST /v1/qualify  |  GET /health  |  GET /docs`);
});
