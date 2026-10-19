import {
  LeadReplySchema,
  SupportReplySchema,
  type LeadReply,
  type SupportReply,
} from "../schemas/reply.js";
import {
  brandContextSummary,
  type BrandContext,
} from "./brand.js";
import { structuredComplete } from "./structured.js";

/**
 * Crafts a high-converting lead reply using only local brand_context.json.
 */
export async function craftLeadReply(
  message: string,
  brand: BrandContext,
): Promise<LeadReply> {
  const kb = brandContextSummary(brand);

  return structuredComplete({
    system: [
      "You are the brand's autonomous first-responder for hot leads.",
      "Use ONLY the brand knowledge base below — do not invent prices or packages.",
      "Match the brand tone. Keep it concise and conversion-oriented.",
      "Do NOT include the checkout URL in the reply text; it will be appended separately.",
      "",
      "=== BRAND KNOWLEDGE BASE (brand_context.json) ===",
      kb,
      "=== END KNOWLEDGE BASE ===",
    ].join("\n"),
    user: `Lead DM:\n"""${message}"""\n\nWrite a personalized reply and pick the best package.`,
    schema: LeadReplySchema,
    toolName: "craft_lead_reply",
    toolDescription:
      "Generate a personalized lead reply and recommended package from brand context.",
    maxTokens: 1024,
  });
}

/**
 * Generates a polite human-handoff message for support requests.
 */
export async function craftSupportReply(
  message: string,
  brand: BrandContext,
): Promise<SupportReply> {
  return structuredComplete({
    system: [
      `You reply as ${brand.brand_name}'s DM assistant.`,
      "A human agent is taking over. Be polite, brief, and reassuring.",
      "Do not sell packages. Do not invent troubleshooting steps.",
      `Hint: ${brand.support.handoff_message_hint}`,
      `Tone: ${brand.tone.voice}`,
    ].join("\n"),
    user: `Support DM:\n"""${message}"""`,
    schema: SupportReplySchema,
    toolName: "craft_support_reply",
    toolDescription: "Generate a polite human-agent handoff message.",
    maxTokens: 512,
  });
}
