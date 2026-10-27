"use client";

import { useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {safeVideoUrl,type VeaVideoArtifact} from "@/lib/data/vea";
import {
  ArrowLeft,
  ArrowUp,
  MessageSquare,
  Rocket,
} from "lucide-react";
import type {
  ActivityFeedItem as ActivityFeedItemData,
  ChatMetric,
  DraftStatus,
  HitlCardData,
  SquadMessageData,
  WorkspaceAgent,
} from "@/lib/data/workspace";

export interface ChatBubbleMessage {
  id: string;
  role: "user" | "agent";
  content: string;
}

export function WorkspaceHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <header className="flex min-h-16 shrink-0 flex-col justify-center gap-1 border-b border-border bg-white px-4 py-3 pl-14 md:flex-row md:items-baseline md:justify-start md:gap-3 md:px-10 md:pt-5">
      <h1 className="min-w-0 break-words font-workspace-display text-[22px] font-extrabold tracking-normal text-[#111111]">
        {title}
      </h1>
      {subtitle && (
        <span className="font-workspace-mono text-[12px] italic text-text-muted">
          {subtitle}
        </span>
      )}
    </header>
  );
}

export function AgentAvatar({
  mark,
  color,
  size = "md",
}: {
  mark: string;
  color: string;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <span
      className={clsx(
        "flex shrink-0 items-center justify-center rounded-[14px] font-workspace-display font-extrabold text-white",
        size === "sm" && "h-[30px] w-[30px] rounded-[9px] text-[12px]",
        size === "md" && "h-[46px] w-[46px] text-[18px]",
        size === "lg" && "h-12 w-12 text-[19px]",
      )}
      style={{ backgroundColor: color }}
    >
      {mark}
    </span>
  );
}

export function AgentCard({ agent }: { agent: WorkspaceAgent }) {
  return (
    <Link
      href={`/agents/${agent.id}`}
      className="group rounded-[18px] border border-[#e5e5e5] bg-white p-6 font-workspace-sans transition-all duration-150 hover:-translate-y-[3px] hover:border-black"
    >
      <AgentAvatar mark={agent.name[0]} color={agent.color} />
      <h2 className="mt-4 font-workspace-display text-[18px] font-bold tracking-[-0.01em] text-[#111111]">
        {agent.name}
      </h2>
      <p className="mt-1 font-workspace-mono text-[10px] uppercase tracking-[0.06em] text-[#999999]">
        {agent.roleLabel}
      </p>
      <div className="mt-4 flex items-center gap-2 text-[12px] text-[#666666]">
        <span className="h-1.5 w-1.5 rounded-full bg-sleyz" />
        {agent.statusLabel}
      </div>
      <p className="mt-2 text-[12px] text-[#666666]">
        {agent.metricText}
      </p>
    </Link>
  );
}

export function SoonAgentCard({ agent }: { agent: WorkspaceAgent }) {
  return (
    <article className="relative rounded-[18px] border border-dashed border-[#d8d8d8] bg-[#fafafa] p-6 font-workspace-sans text-[#111111] opacity-80">
      <div className="flex h-[46px] w-[46px] items-center justify-center rounded-[14px] bg-[#ececec] font-workspace-display text-[18px] font-extrabold text-[#666666]">
        {agent.name[0]}
      </div>
      <div className="mt-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-workspace-display text-[18px] font-bold tracking-[-0.01em]">
            {agent.name}
          </h2>
          <p className="mt-1 font-workspace-mono text-[10px] uppercase tracking-[0.06em] text-[#999999]">
            {agent.roleLabel}
          </p>
        </div>
        <span className="rounded-full bg-[#ececec] px-2 py-1 font-workspace-mono text-[8px] uppercase tracking-[0.08em] text-[#666666]">
          Soon
        </span>
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-[#666666]">
        {agent.role}
      </p>
      <p className="mt-2 text-[12px] leading-relaxed text-[#999999]">
        {agent.metricText}
      </p>
    </article>
  );
}

export function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <article className="rounded-[14px] bg-[#f4f4f5] p-[18px] font-workspace-sans">
      <div className="font-workspace-display text-[26px] font-extrabold tracking-[-0.02em] text-[#111111]">
        {value}
      </div>
      <div className="mt-1 text-[12px] text-[#666666]">{label}</div>
    </article>
  );
}

export function ActivityFeedItem({ item }: { item: ActivityFeedItemData }) {
  return (
    <div className="flex items-start gap-3 border-b border-[#f4f4f5] py-3 font-workspace-sans">
      <span
        className="mt-[5px] h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: item.color }}
      />
      <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-[#111111]">
        {item.text}
      </p>
      <span className="ml-auto whitespace-nowrap font-workspace-mono text-[10px] text-[#999999]">
        {item.timestamp}
      </span>
    </div>
  );
}

export function ChatEmptyState({
  eyebrow,
  color,
  headline,
  accentWord,
  description,
  suggestions,
  metrics,
  onSuggestion,
}: {
  eyebrow: string;
  color: string;
  headline: string;
  accentWord: string;
  description: string;
  suggestions: string[];
  metrics: ChatMetric[];
  onSuggestion: (prompt: string) => void;
}) {
  return (
    <section className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center font-workspace-sans">
      <p
        className="mb-[18px] font-workspace-mono text-[11px] uppercase tracking-[0.1em]"
        style={{ color }}
      >
        {eyebrow}
      </p>
      <h1 className="font-workspace-display text-[clamp(30px,4vw,34px)] font-extrabold tracking-[-0.02em] text-[#111111]">
        {headline}{" "}
        <span style={{ color }}>{accentWord}</span>
      </h1>
      <p className="mt-3 max-w-[480px] text-[14px] leading-[1.6] text-[#666666]">
        {description}
      </p>
      <div className="mt-8 grid w-full max-w-[620px] grid-cols-1 gap-2.5 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onSuggestion(suggestion)}
            className="rounded-xl border border-[#e5e5e5] bg-white px-4 py-3.5 text-left text-[13px] leading-relaxed text-[#111111] transition-colors hover:bg-[#f4f4f5]"
          >
            {suggestion}
          </button>
        ))}
      </div>
      <div className="mt-7 flex flex-wrap justify-center gap-6">
        {metrics.map((metric) => (
          <div key={metric.label} className="text-center">
            <div className="font-workspace-display text-[18px] font-extrabold text-[#111111]">
              {metric.value}
            </div>
            <div className="font-workspace-mono text-[9px] uppercase tracking-[0.06em] text-[#999999]">
              {metric.label}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function ChatThread({
  messages,
  agentColor,
}: {
  messages: ChatBubbleMessage[];
  agentColor: string;
}) {
  return (
    <div className="flex-1 overflow-y-auto px-5 py-5 font-workspace-sans md:px-10">
      <div className="mx-auto flex max-w-3xl flex-col gap-3">
        {messages.map((message) => (
          <div
            key={message.id}
            className={clsx(
              "max-w-[75%] whitespace-pre-wrap rounded-[14px] px-3.5 py-2.5 text-[13px] leading-[1.5]",
              message.role === "user"
                ? "ml-auto rounded-br bg-black text-white"
                : "mr-auto rounded-bl bg-[#f4f4f5] text-[#111111]",
            )}
            style={message.role === "agent" ? { borderLeft: `3px solid ${agentColor}` } : undefined}
          >
            {message.content}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChatInputBar({
  placeholder,
  showTaskToggle = true,
  isSending = false,
  onSend,
}: {
  placeholder: string;
  showTaskToggle?: boolean;
  isSending?: boolean;
  onSend: (message: string) => void | Promise<void>;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const text = value.trim();
    if (!text || isSending) return;
    setValue("");
    void onSend(text);
  }

  return (
    <div className="shrink-0 px-5 pb-6 font-workspace-sans md:px-10">
      <div className="mx-auto max-w-3xl rounded-2xl border border-[#e5e5e5] bg-white px-4 py-3">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
          }}
          placeholder={placeholder}
          disabled={isSending}
          className="mb-2.5 w-full bg-transparent text-[14px] font-light text-[#111111] outline-none placeholder:text-[#999999]"
        />
        <div className="flex items-center justify-between">
          {showTaskToggle ? (
            <div className="flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[#e5e5e5] bg-[#f4f4f5] px-2.5 py-1 font-workspace-mono text-[10px] text-[#111111]">
                <MessageSquare size={11} />
                Chat
              </span>
              <span
                aria-disabled="true"
                className="inline-flex items-center gap-1.5 rounded-full border border-[#e5e5e5] px-2.5 py-1 font-workspace-mono text-[10px] text-[#666666]"
              >
                <Rocket size={11} />
                Task
              </span>
            </div>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={submit}
            disabled={isSending}
            className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-black text-white transition-transform hover:scale-[1.03] active:scale-[0.95] disabled:cursor-not-allowed disabled:bg-[#d4d4d4]"
            aria-label="Send"
          >
            <ArrowUp size={15} strokeWidth={2.4} />
          </button>
        </div>
      </div>
    </div>
  );
}

function mentionParts(text: string) {
  return text.split(/(@[A-Za-z]+)/g).filter(Boolean);
}

export function SquadMessage({
  message,
  hitlStatus,
  onHitlAction,
  onResolve,
  onDeliver,
  onRetry,
  onRefresh,
  onRetryLearning,
  busy,
}: {
  message: SquadMessageData;
  hitlStatus?: DraftStatus;
  onHitlAction?: (status: DraftStatus, finalContent?: string) => void;
  onResolve?: () => void;
  onDeliver?: () => void;
  onRetry?: () => void;
  onRefresh?: () => void;
  onRetryLearning?: () => void;
  busy?: boolean;
}) {
  return (
    <article className="flex items-start gap-2.5 font-workspace-sans">
      <AgentAvatar mark={message.mark} color={message.senderColor} size="sm" />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-[12px] font-medium text-[#111111]">{message.sender}</span>
          <span className="font-workspace-mono text-[9px] text-[#999999]">
            {message.timestamp}
          </span>
        </div>
        <p className="whitespace-pre-wrap text-[13px] leading-[1.5] text-[#111111]">
          {mentionParts(message.text).map((part, index) =>
            part.startsWith("@") ? (
              <span key={`${part}-${index}`} className="font-medium text-converza-blue">
                {part}
              </span>
            ) : (
              <span key={`${part}-${index}`}>{part}</span>
            ),
          )}
        </p>
        {message.hitlCard && (
          <HitlCard
            card={{ ...message.hitlCard, status: hitlStatus ?? message.hitlCard.status }}
            onApprove={() => onHitlAction?.("approved")}
            onEdit={(finalContent) => onHitlAction?.("edited", finalContent)}
            onSkip={() => onHitlAction?.("rejected")}
            onResolve={onResolve}
            onDeliver={onDeliver}
            onRetry={onRetry}
            onRefresh={onRefresh}
            onRetryLearning={onRetryLearning}
            busy={busy}
          />
        )}
      </div>
    </article>
  );
}

export function HitlCard({
  card,
  onApprove,
  onEdit,
  onSkip,
  onResolve,
  onDeliver,
  onRetry,
  onRefresh,
  onRetryLearning,
  busy,
}: {
  card: HitlCardData;
  onApprove: () => void;
  onEdit: (finalContent: string) => void;
  onSkip: () => void;
  onResolve?: () => void;
  onDeliver?: () => void;
  onRetry?: () => void;
  onRefresh?: () => void;
  onRetryLearning?: () => void;
  busy?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState(card.content);
  if(card.veaArtifact)return <div className="mt-2 space-y-3 rounded-xl border border-border p-4 text-xs">
    <VeaPreview artifact={card.veaArtifact}/>
    {card.supersededBy||card.veaArtifact.superseded?<p>Replaced by a new video revision. Review the replacement.</p>:<>
      {card.status==='pending'&&<div className="flex flex-wrap gap-2"><button disabled={busy||!safeVideoUrl(card.veaArtifact.video_url)} onClick={onApprove} className="rounded-full bg-black px-3 py-2 text-white disabled:opacity-50">Approve &amp; Export</button><button disabled={busy} onClick={onSkip} className="rounded-full border border-border px-3 py-2">Reject</button></div>}
      {card.status==='approved'&&<p>Approved for export · <a href={safeVideoUrl(card.veaArtifact.video_url)} download target="_blank" rel="noopener noreferrer" className="underline">Download MP4</a></p>}
      {card.status==='rejected'&&<p>Video rejected</p>}
      <a href={`/agents/vea#video-${encodeURIComponent(card.veaArtifact.id)}`} className="inline-block underline">Review clips in Vea · Swap Clip &amp; Re-render</a>
    </>}
  </div>;
  const resolved = card.status !== "pending" || !!card.supersededBy;
  const canSubmitEdit = editText.trim().length > 0;
  const statusClass = {
    approved: "bg-sleyz-dim text-sleyz",
    edited: "bg-milo-dim text-milo",
    rejected: "bg-[#f4f4f5] text-[#666666]",
    pending: "",
    published: "bg-sleyz-dim text-sleyz",
    generating: "bg-[#f4f4f5] text-[#666666]",
  }[card.status];
  const statusLabel = {
    approved: "Approved · awaiting publisher",
    edited: "Edited · awaiting publisher",
    rejected: "Skipped",
    pending: "",
    published: card.resolvedAt ? "Delivered · conversation resolved" : "Published · delivery confirmed",
    generating: card.generationError ? "Generation failed" : "Generating draft",
  }[card.status];

  return (
    <div className="mt-2 rounded-xl border border-[#e5e5e5] bg-white px-4 py-3.5">
      <div className="font-workspace-mono text-[9px] uppercase tracking-[0.06em] text-[#999999]">
        {card.label}
      </div>
      {card.simulated && <p className="mt-2 text-xs font-medium text-milo">Simulation · customer delivery and learning disabled</p>}
      {card.supersededBy && <p className="mt-2 text-xs text-text-muted">Replaced by a refreshed draft. Review the replacement before sending.</p>}
      {card.artifact && <div className="mt-3 space-y-2 border-y border-border py-3 text-xs">
        <p><span className="font-medium">{card.artifact.intent} · {Math.round(card.artifact.intent_score * 100)}% readiness</span> · {card.artifact.platform} · {card.artifact.customer_handle}</p>
        <p className="whitespace-pre-wrap text-text-secondary">Buyer: {card.artifact.incoming_message}</p>
        {card.artifact.detected_objection && <p>Objection: {card.artifact.detected_objection}</p>}
        {card.artifact.product_snapshot.map(product => <p key={product.id}>{product.name}{product.sku ? ` · ${product.sku}` : ""} · {product.price === null ? "Price unknown" : `${product.currency} ${product.price}`} · {product.stock_count === null ? "Stock unknown" : `${product.stock_count} in stock`} · quantity {card.artifact!.quantity}</p>)}
        {card.artifact.checkout_link && <a href={card.artifact.checkout_link} target="_blank" rel="noopener noreferrer" className="block break-all text-converza-blue underline">Checkout: {card.artifact.checkout_link}</a>}
        {card.artifact.operator_notes.map((note,index) => <p key={index} className="text-milo">{note}</p>)}
        <details><summary className="cursor-pointer text-text-secondary">Evidence ({card.artifact.cited_brand_passport_atoms.length}) and original draft</summary>
          {card.artifact.cited_brand_passport_atoms.map((citation,index) => <p key={index} className="mt-2 break-all font-mono">Source {citation.source_id} · revision {citation.revision}{citation.atom_index != null ? ` · Atom ${citation.atom_index}` : ""}{citation.span ? ` · span ${citation.span.join("–")}` : ""}</p>)}
          <p className="mt-2 whitespace-pre-wrap text-text-muted">{card.artifact.draft_reply}</p>
        </details>
      </div>}
      <p className="mt-2 whitespace-pre-wrap text-[13px] leading-[1.5] text-[#111111]">
        {card.content}
      </p>
      {card.generationError&&<p role="alert" className="mt-2 text-xs text-error">{card.generationError}</p>}
      {card.deliveryError&&<p role="alert" className="mt-2 text-xs text-error">Delivery {card.deliveryStatus}: {card.deliveryError}</p>}
      {card.deliveryStatus==="sending"&&<p className="mt-2 text-xs text-text-muted">Delivery in progress</p>}
      {card.deliveryStatus==="ambiguous"&&<p className="mt-2 text-xs text-milo">Delivery confirmation is uncertain. Check the channel before taking further action.</p>}
      {card.learningStatus&&<p className="mt-2 text-xs text-text-muted">Correction learning: {card.learningStatus}</p>}
      {card.learningError&&<p role="alert" className="mt-2 text-xs text-error">{card.learningError}</p>}
      {!resolved && isEditing && (
        <div className="mt-3">
          <label className="mb-1.5 block font-workspace-mono text-[9px] uppercase tracking-[0.08em] text-[#999999]">
            Replacement content
          </label>
          <textarea
            value={editText}
            onChange={(event) => setEditText(event.target.value)}
            rows={4}
            className="w-full resize-none rounded-xl border border-[#e5e5e5] bg-[#fafafa] px-3 py-2.5 text-[12.5px] leading-[1.5] text-[#111111] outline-none transition-colors placeholder:text-[#999999] focus:border-converza-blue focus:bg-white"
            placeholder="Type the exact version you want saved..."
          />
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {card.canDeliver&&<button disabled={busy} onClick={onDeliver} className="rounded-full border border-border px-3 py-1.5 text-xs disabled:opacity-50">{card.deliveryStatus==="failed"?"Retry delivery":"Send buyer reply"}</button>}
        {card.canResolve&&<button disabled={busy} onClick={onResolve} className="rounded-full border border-border px-3 py-1.5 text-xs disabled:opacity-50">Mark conversation resolved</button>}
        {card.generationError&&onRetry&&<button disabled={busy} onClick={onRetry} className="rounded-full border border-border px-3 py-1.5 text-xs disabled:opacity-50">Retry generation</button>}
        {card.canRefresh&&onRefresh&&<button disabled={busy} onClick={onRefresh} className="rounded-full border border-border px-3 py-1.5 text-xs disabled:opacity-50">Refresh draft for new approval</button>}
        {card.learningStatus==="failed"&&onRetryLearning&&<button disabled={busy} onClick={onRetryLearning} className="rounded-full border border-border px-3 py-1.5 text-xs disabled:opacity-50">Retry learning</button>}
        {resolved ? (
          <span className={clsx("rounded-full px-2.5 py-1 font-workspace-mono text-[10px]", statusClass)}>
            {statusLabel}
          </span>
        ) : (
          <>
            <button
              type="button"
              onClick={onApprove}
              disabled={busy}
              className="rounded-full border border-converza-blue bg-converza-blue px-3.5 py-1.5 text-[11px] font-medium text-white"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => {
                if (!isEditing) {
                  setIsEditing(true);
                  return;
                }
                if (canSubmitEdit) onEdit(editText.trim());
              }}
              disabled={busy || (isEditing && !canSubmitEdit)}
              className="rounded-full border border-[#e5e5e5] px-3.5 py-1.5 text-[11px] text-[#111111] hover:bg-[#f4f4f5] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isEditing ? "Submit edit" : "Request edit"}
            </button>
            {isEditing && (
              <button
                type="button"
                onClick={() => {
                  setIsEditing(false);
                  setEditText(card.content);
                }}
                className="rounded-full border border-[#e5e5e5] px-3.5 py-1.5 text-[11px] text-[#666666] hover:bg-[#f4f4f5]"
              >
                Cancel
              </button>
            )}
            <button
              type="button"
              onClick={onSkip}
              disabled={busy}
              className="rounded-full border border-[#e5e5e5] px-3.5 py-1.5 text-[11px] text-[#111111] hover:bg-[#f4f4f5]"
            >
              Skip
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export function VeaPreview({artifact}:{artifact:VeaVideoArtifact}){
 const url=safeVideoUrl(artifact.video_url);
 return <div className="space-y-2"><p className="text-xs font-medium">{artifact.preset_used} · {artifact.duration_sec.toFixed(1)}s · Revision {artifact.variant_revision}</p>
  {url?<video controls playsInline preload="metadata" poster={safeVideoUrl(artifact.thumbnail_url)} src={url} className="max-h-[480px] w-full rounded-lg bg-black" aria-label="Rendered video preview"/>:<p role="alert" className="text-xs text-error">Video preview unavailable. Refresh to retrieve the media.</p>}
 </div>;
}

export function AgentBackLink() {
  return (
    <Link
      href="/agents"
      className="inline-flex items-center gap-1.5 pl-14 pr-5 pt-4 font-workspace-mono text-[11px] text-[#999999] transition-colors hover:text-[#111111] md:px-10"
    >
      <ArrowLeft size={12} />
      back to agents
    </Link>
  );
}
