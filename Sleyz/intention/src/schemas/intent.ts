import { z } from "zod";

export const IntentEnum = z.enum([
  "LEAD_HOT",
  "SUPPORT_REQUEST",
  "SPAM_OR_TRASH",
]);

export type Intent = z.infer<typeof IntentEnum>;

/** Strict structured-output schema for LLM intent classification. */
export const IntentClassificationSchema = z.object({
  intent: IntentEnum.describe(
    "Exactly one of: LEAD_HOT (pricing/service interest), SUPPORT_REQUEST (technical/human help), SPAM_OR_TRASH (negative, spam, or irrelevant)",
  ),
  confidence: z
    .number()
    .describe("Model confidence between 0 and 1"),
  rationale: z
    .string()
    .describe("One short sentence explaining why this intent was chosen"),
});

export type IntentClassification = z.infer<typeof IntentClassificationSchema>;
