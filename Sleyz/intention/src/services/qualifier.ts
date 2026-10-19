import type { QualifierResponse } from "../schemas/api.js";
import { loadBrandContext } from "./brand.js";
import { classifyIntent } from "./classifier.js";
import { craftLeadReply, craftSupportReply } from "./responder.js";

/**
 * Autonomous first-responder pipeline:
 * 1) Classify intent via LLM structured outputs
 * 2) Execute the matching branch using local brand_context.json
 */
export async function qualifyMessage(
  message: string,
): Promise<QualifierResponse> {
  const brand = loadBrandContext();
  const classification = await classifyIntent(message);

  switch (classification.intent) {
    case "LEAD_HOT": {
      const lead = await craftLeadReply(message, brand);
      const replyWithCheckout = `${lead.reply.trim()}\n\nCheckout: ${brand.checkout.mock_link}`;
      return {
        intent: "LEAD_HOT",
        status: "REPLIED",
        reply: replyWithCheckout,
        checkout_link: brand.checkout.mock_link,
        confidence: classification.confidence,
        rationale: classification.rationale,
        brand: brand.brand_name,
      };
    }

    case "SUPPORT_REQUEST": {
      const support = await craftSupportReply(message, brand);
      return {
        intent: "SUPPORT_REQUEST",
        status: "HANDED_OFF",
        reply: support.reply.trim(),
        checkout_link: null,
        confidence: classification.confidence,
        rationale: classification.rationale,
        brand: brand.brand_name,
      };
    }

    case "SPAM_OR_TRASH":
      return {
        intent: "SPAM_OR_TRASH",
        status: "IGNORE",
        reply: null,
        checkout_link: null,
        confidence: classification.confidence,
        rationale: classification.rationale,
        brand: brand.brand_name,
      };
  }
}
