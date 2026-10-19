import { Router } from "express";
import {
  IncomingMessageSchema,
  QualifierResponseSchema,
} from "../schemas/api.js";
import { formatQualifyError } from "../lib/errors.js";
import { qualifyMessage } from "../services/qualifier.js";

export const qualifyRouter = Router();

/**
 * POST /v1/qualify
 * Body: { "message": string, "sender_id"?: string, "channel"?: string }
 * Returns raw structured JSON only.
 */
qualifyRouter.post("/qualify", async (req, res) => {
  const parsed = IncomingMessageSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({
      error: "invalid_request",
      details: parsed.error.flatten(),
    });
    return;
  }

  try {
    const result = await qualifyMessage(parsed.data.message);
    const validated = QualifierResponseSchema.parse(result);
    res.status(200).json(validated);
  } catch (err) {
    const { status, error, message } = formatQualifyError(err);
    res.status(status).json({ error, message });
  }
});
