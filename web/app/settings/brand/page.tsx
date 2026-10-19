"use client";

import { useEffect, useState } from "react";
import { memoryRequest, downloadIdentity, type IdentityCore } from "@/lib/api/memory";

const BRAND_NAME_STORAGE_KEY = "converza.brandName";

export default function BrandPage() {
  const [brandName, setBrandName] = useState("");
  const [voice, setVoice] = useState("");
  const [audience, setAudience] = useState("");
  const [promise, setPromise] = useState("");
  const [markets, setMarkets] = useState<string[]>([]);
  const [negative, setNegative] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState("");
  const [newMarket, setNewMarket] = useState("");

  useEffect(() => {
    void memoryRequest<IdentityCore>("/identity").then(core=>{
      const passport=core.passport;
      setBrandName(String(passport.brand_name??""));
      const voiceRules=passport.voice_rules??passport.tone??passport.brand_voice??"";
      setVoice(Array.isArray(voiceRules)?voiceRules.join("\n"):String(voiceRules));
      setAudience(String(passport.target_audience??""));
      setPromise(String(passport.core_offer??""));
      setMarkets(String(passport.target_location??"").split(",").map(value=>value.trim()).filter(Boolean));
      const constraints=passport.negative_constraints??"";
      setNegative(Array.isArray(constraints)?constraints.join("\n"):String(constraints));setRevision(core.revision);
    }).catch(error=>setMessage(error.message)).finally(()=>setBusy(false));
  }, []);

  async function save(){
    setBusy(true);setMessage("");
    try{
      const core=await memoryRequest<IdentityCore>("/identity",{method:"PUT",body:JSON.stringify({brand_name:brandName.trim(),voice_rules:voice,tone:voice,target_audience:audience,core_offer:promise,target_location:markets.join(", "),negative_constraints:negative,revision})});
      setRevision(core.revision);setMessage("Saved. All agents use this identity on their next run.");
      window.localStorage.setItem(BRAND_NAME_STORAGE_KEY, brandName.trim());
      window.dispatchEvent(new Event("converza:brand-name-updated"));
    }catch(error){setMessage(error instanceof Error?error.message:"Save failed");}finally{setBusy(false);}
  }

  function addMarket() {
    const v = newMarket.trim();
    if (!v) return;
    setMarkets((m) => [...m, v]);
    setNewMarket("");
  }

  return (
    <div className="space-y-12">
      <header>
        <h2 className="text-[28px] font-medium tracking-[-0.025em] text-text-primary">
          Brand passport
        </h2>
        <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
          The single source of truth the swarm reads before generating anything. Captured once, reused on every run.
        </p>
      </header>

      {message&&<p role="status" className="rounded-lg border border-border p-3 text-sm">{message}</p>}

      <Field label="Brand name" hint="Shown in the sidebar and used as the workspace identity.">
        <input
          value={brandName}
          onChange={(e) => setBrandName(e.target.value)}
          className="w-full rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-[14px] text-text-primary outline-none transition-all focus:border-text-primary focus:shadow-[0_0_0_4px_rgba(0,0,0,0.04)]"
        />
      </Field>

      <Field label="Voice & tone" hint="Three to five adjectives. The way the brand sounds in writing.">
        <textarea
          rows={2}
          value={voice}
          onChange={(e) => setVoice(e.target.value)}
          className="w-full resize-none rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-[14px] leading-relaxed text-text-primary outline-none transition-all focus:border-text-primary focus:shadow-[0_0_0_4px_rgba(0,0,0,0.04)]"
        />
      </Field>

      <Field label="Audience" hint="The buyer in one sentence — who they are, what they want.">
        <textarea
          rows={2}
          value={audience}
          onChange={(e) => setAudience(e.target.value)}
          className="w-full resize-none rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-[14px] leading-relaxed text-text-primary outline-none transition-all focus:border-text-primary focus:shadow-[0_0_0_4px_rgba(0,0,0,0.04)]"
        />
      </Field>

      <Field label="Core promise" hint="What the brand actually delivers — the line on the box.">
        <input
          value={promise}
          onChange={(e) => setPromise(e.target.value)}
          className="w-full rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-[14px] text-text-primary outline-none transition-all focus:border-text-primary focus:shadow-[0_0_0_4px_rgba(0,0,0,0.04)]"
        />
      </Field>

      <Field label="Markets" hint="Where the ads should run. Each market gets its own copy register.">
        <div className="flex flex-wrap items-center gap-2">
          {markets.map((m) => (
            <span
              key={m}
              className="inline-flex items-center gap-2 rounded-full border border-border bg-bg-elevated px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-text-primary"
            >
              {m}
              <button
                onClick={() => setMarkets((arr) => arr.filter((x) => x !== m))}
                className="text-text-muted hover:text-error"
                aria-label={`Remove ${m}`}
              >
                ×
              </button>
            </span>
          ))}
          <input
            placeholder="Add market…"
            value={newMarket}
            onChange={(e) => setNewMarket(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addMarket()}
            className="rounded-full border border-dashed border-border bg-transparent px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-text-secondary outline-none placeholder-text-muted/70 focus:border-text-primary"
          />
        </div>
      </Field>

      <Field label="Negative constraints" hint="Claims, phrases, and behaviors the agents must avoid.">
        <textarea aria-label="Negative constraints" value={negative} onChange={event=>setNegative(event.target.value)} rows={4} className="w-full rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-sm" />
      </Field>

      <div className="flex flex-wrap gap-4 text-xs">{["brand_passport.md","voice_rules.md","negative_constraints.md"].map(name=><button key={name} onClick={()=>void downloadIdentity(name).catch(error=>setMessage(error.message))} className="underline">Export {name}</button>)}</div>

      <div className="flex items-center justify-between border-t border-border pt-6">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted">
          Identity revision {revision}
        </span>
        <button onClick={()=>void save()} disabled={busy||!brandName.trim()} className="rounded-full bg-text-primary px-5 py-2.5 text-[13.5px] font-medium text-bg-elevated transition-all hover:scale-[1.02] active:scale-[0.97] disabled:opacity-50">
          {busy?"Saving…":"Save changes"}
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1.6fr] md:gap-10">
      <div>
        <div className="text-[14px] font-medium text-text-primary">{label}</div>
        {hint && (
          <div className="mt-1 text-[12.5px] leading-relaxed text-text-muted">
            {hint}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}
