/** OpenAPI 3.0 spec — mirrors FastAPI /docs from converza-lead-qualifier. */
export const openApiSpec = {
  openapi: "3.0.3",
  info: {
    title: "Converza — Autonomous Revenue Team",
    description:
      "AI first-responder for inbound DMs. Part of the Converza platform — https://getconverza.com",
    version: "1.0.0",
  },
  paths: {
    "/health": {
      get: {
        tags: ["default"],
        summary: "Health",
        operationId: "health_health_get",
        responses: {
          "200": {
            description: "Successful Response",
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    ok: { type: "boolean", example: true },
                    service: { type: "string", example: "converza" },
                    brand: { type: "string", example: "Converza" },
                  },
                },
              },
            },
          },
        },
      },
    },
    "/v1/qualify": {
      post: {
        tags: ["default"],
        summary: "Qualify",
        operationId: "qualify_v1_qualify_post",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/IncomingMessage" },
            },
          },
        },
        responses: {
          "200": {
            description: "Successful Response",
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/QualifierResponse" },
              },
            },
          },
          "400": {
            description: "Validation Error",
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/HTTPValidationError" },
              },
            },
          },
          "402": { description: "Billing Error" },
          "502": { description: "Upstream Error" },
        },
      },
    },
  },
  components: {
    schemas: {
      IncomingMessage: {
        type: "object",
        required: ["message"],
        properties: {
          message: {
            type: "string",
            minLength: 1,
            description: "Raw text of the inbound message",
            example: "Hey, how much for your marketing package?",
          },
          sender_id: {
            type: "string",
            description: "Optional sender identifier",
          },
          channel: {
            type: "string",
            default: "dm",
            description: "Source channel",
          },
        },
      },
      QualifierResponse: {
        type: "object",
        required: [
          "intent",
          "status",
          "reply",
          "checkout_link",
          "confidence",
          "rationale",
          "brand",
        ],
        properties: {
          intent: { $ref: "#/components/schemas/IntentEnum" },
          status: {
            type: "string",
            enum: ["REPLIED", "HANDED_OFF", "IGNORE"],
          },
          reply: { type: "string", nullable: true },
          checkout_link: { type: "string", nullable: true },
          confidence: { type: "number", minimum: 0, maximum: 1 },
          rationale: { type: "string" },
          brand: { type: "string" },
        },
        example: {
          intent: "LEAD_HOT",
          status: "REPLIED",
          reply: "Thanks for reaching out! Our Growth Sprint package starts at $2,400/mo…",
          checkout_link:
            "https://getconverza.com/org/subscription/checkout?utm_source=dm&utm_medium=converza",
          confidence: 0.93,
          rationale: "User asked about pricing for a marketing package.",
          brand: "Converza",
        },
      },
      IntentEnum: {
        type: "string",
        enum: ["LEAD_HOT", "SUPPORT_REQUEST", "SPAM_OR_TRASH"],
      },
      HTTPValidationError: {
        type: "object",
        properties: {
          error: { type: "string", example: "invalid_request" },
          details: { type: "object" },
        },
      },
    },
  },
} as const;
