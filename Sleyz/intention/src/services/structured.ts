import type { ZodType } from "zod";
import { z } from "zod";
import { extractJSON } from "./gateway.js";

/** Strict extraction through the shared Huawei client, followed by local schema validation. */
export async function structuredComplete<T>(options: {
  system: string; user: string; schema: ZodType<T>; toolName: string;
  toolDescription: string; maxTokens?: number;
}): Promise<T> {
  const outputSchema=z.toJSONSchema(options.schema as z.ZodType,{target:"draft-7"}) as Record<string,unknown>;
  const result=await extractJSON([
    {role:"system",content:`${options.system}\n${options.toolDescription}\nReturn JSON only, matching this schema: ${JSON.stringify(outputSchema)}`},
    {role:"user",content:options.user},
  ],outputSchema,options.maxTokens??1024);
  return options.schema.parse(result);
}
