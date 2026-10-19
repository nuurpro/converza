import { z } from "zod";

/** Strict structured-output schema for LLM lead reply generation. */
export const LeadReplySchema = z.object({
  reply: z
    .string()
    .describe(
      "Personalized DM reply matching brand tone. Must mention relevant package/pricing when appropriate and invite next step.",
    ),
  recommended_package: z
    .string()
    .describe("Package name from brand context that best fits the lead"),
});

export type LeadReply = z.infer<typeof LeadReplySchema>;

/** Strict structured-output schema for support handoff messages. */
export const SupportReplySchema = z.object({
  reply: z
    .string()
    .describe(
      "Polite message confirming a human agent is taking over. No sales pitch.",
    ),
});

export type SupportReply = z.infer<typeof SupportReplySchema>;
