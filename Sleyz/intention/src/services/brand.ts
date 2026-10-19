import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const BrandContextSchema = z.object({
  brand_name: z.string(),
  tagline: z.string(),
  industry: z.string(),
  website: z.string().url().optional(),
  tone: z.object({
    voice: z.string(),
    style_notes: z.array(z.string()),
    example_phrases: z.array(z.string()),
  }),
  services: z.array(
    z.object({
      name: z.string(),
      description: z.string(),
      price_from: z.number(),
      currency: z.string(),
      billing: z.string(),
    }),
  ),
  faqs: z.array(
    z.object({
      question: z.string(),
      answer: z.string(),
    }),
  ),
  checkout: z.object({
    base_url: z.string(),
    default_package: z.string(),
    mock_link: z.string(),
  }),
  support: z.object({
    handoff_message_hint: z.string(),
  }),
});

export type BrandContext = z.infer<typeof BrandContextSchema>;

const __dirname = dirname(fileURLToPath(import.meta.url));

let cached: BrandContext | null = null;

/**
 * Strictly loads brand knowledge from the local brand_context.json file.
 * No remote KB / hardcoded fallbacks beyond file path resolution.
 */
export function loadBrandContext(): BrandContext {
  if (cached) return cached;

  const candidates = [
    join(process.cwd(), "brand_context.json"),
    join(__dirname, "../../brand_context.json"),
  ];

  let raw: string | null = null;
  for (const path of candidates) {
    try {
      raw = readFileSync(path, "utf-8");
      break;
    } catch {
      // try next
    }
  }

  if (!raw) {
    throw new Error(
      "Unable to load brand_context.json — ensure it exists in the project root",
    );
  }

  cached = BrandContextSchema.parse(JSON.parse(raw));
  return cached;
}

export function brandContextSummary(brand: BrandContext): string {
  const services = brand.services
    .map(
      (s) =>
        `- ${s.name}: ${s.description} (from ${s.price_from} ${s.currency} ${s.billing})`,
    )
    .join("\n");

  const faqs = brand.faqs
    .map((f) => `Q: ${f.question}\nA: ${f.answer}`)
    .join("\n");

  return [
    `Brand: ${brand.brand_name}`,
    `Tagline: ${brand.tagline}`,
    `Industry: ${brand.industry}`,
    `Tone/voice: ${brand.tone.voice}`,
    `Style notes: ${brand.tone.style_notes.join("; ")}`,
    `Example phrases: ${brand.tone.example_phrases.join(" | ")}`,
    `Services:\n${services}`,
    `FAQs:\n${faqs}`,
    `Default checkout link: ${brand.checkout.mock_link}`,
  ].join("\n");
}
