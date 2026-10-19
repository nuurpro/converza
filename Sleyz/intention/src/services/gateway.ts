type Message = { role: "system" | "user" | "assistant"; content: string };

/** Provider selection, credentials, temperatures and retries stay in the Python service. */
export async function extractJSON(messages: Message[], outputSchema: Record<string, unknown>, maxTokens: number): Promise<unknown> {
  const key=process.env.LLM_SERVICE_API_KEY;
  if(!key)throw new Error("LLM_SERVICE_API_KEY is required for the shared Huawei inference service");
  const base=(process.env.CONVERZA_LLM_URL??"http://127.0.0.1:8000").replace(/\/$/,"");
  const response=await fetch(`${base}/api/internal/llm/extract`,{
    method:"POST",headers:{"Content-Type":"application/json","x-llm-service-key":key},
    body:JSON.stringify({messages,output_schema:outputSchema,max_tokens:maxTokens}),
    signal:AbortSignal.timeout(600000),
  });
  if(!response.ok)throw new Error(`Shared Huawei extraction failed (${response.status})`);
  return response.json();
}
