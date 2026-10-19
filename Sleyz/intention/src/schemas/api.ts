import { z } from "zod";
import { IntentEnum } from "./intent.js";

export const IncomingMessageSchema = z.object({
  message: z.string().min(1, "message is required"),
  sender_id: z.string().optional(),
  channel: z.string().optional().default("dm"),
});

export type IncomingMessage = z.infer<typeof IncomingMessageSchema>;

export const QualifierResponseSchema = z.object({
  intent: IntentEnum,
  status: z.enum(["REPLIED", "HANDED_OFF", "IGNORE"]),
  reply: z.string().nullable(),
  checkout_link: z.string().nullable(),
  confidence: z.number(),
  rationale: z.string(),
  brand: z.string(),
});

export type QualifierResponse = z.infer<typeof QualifierResponseSchema>;
