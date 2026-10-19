import {
  IntentClassificationSchema,
  type IntentClassification,
} from "../schemas/intent.js";
import { structuredComplete } from "./structured.js";

/**
 * Classifies an inbound DM into one of three strict intents using
 * Huawei through the shared Python service with JSON Schema + Zod validation.
 */
export async function classifyIntent(
  message: string,
): Promise<IntentClassification> {
  return structuredComplete({
    system: [
      "You are an intent classifier for brand DMs.",
      "Choose exactly one intent:",
      "- LEAD_HOT: explicit interest in services, pricing, packages, demos, or buying.",
      "- SUPPORT_REQUEST: technical issues, account problems, or requests for a human.",
      "- SPAM_OR_TRASH: insults, unsubscribe/stop messages, bot spam, or irrelevant noise.",
      "Return only structured fields. No prose outside the schema.",
    ].join("\n"),
    user: `Incoming DM:\n"""${message}"""`,
    schema: IntentClassificationSchema,
    toolName: "classify_intent",
    toolDescription: "Classify the inbound brand DM into a strict intent bucket.",
    maxTokens: 512,
  });
}
