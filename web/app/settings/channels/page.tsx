import { Instagram, MessageCircle, Send, Video, Workflow } from "lucide-react";

const channels = [
  { name: "Telegram", icon: Send, note: "Business connection will be wired in Phase B." },
  { name: "Instagram", icon: Instagram, note: "DM and profile connection is coming next." },
  { name: "TikTok", icon: Video, note: "Ad account and organic posting connection placeholder." },
  { name: "WhatsApp", icon: MessageCircle, note: "Inbox routing will live here later." },
  { name: "Website chat", icon: Workflow, note: "Site widget connection placeholder." },
];

export default function ChannelsSettingsPage() {
  return (
    <section>
      <div className="mb-8">
        <h2 className="text-[24px] font-medium tracking-[-0.02em] text-text-primary">
          Channels
        </h2>
        <p className="mt-2 max-w-xl text-[14px] leading-relaxed text-text-secondary">
          Channel connections are not active yet. This page shows where Telegram, Instagram,
          TikTok, WhatsApp, and website chat setup will live.
        </p>
      </div>

      <div className="grid gap-3">
        {channels.map((channel) => (
          <article
            key={channel.name}
            className="flex items-center gap-4 rounded-2xl border border-border bg-bg-elevated p-5"
          >
            <span className="grid h-11 w-11 place-items-center rounded-xl border border-border bg-bg-secondary text-text-secondary">
              <channel.icon size={18} strokeWidth={1.8} />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-[15px] font-medium text-text-primary">{channel.name}</h3>
              <p className="mt-1 text-[13px] text-text-secondary">{channel.note}</p>
            </div>
            <span className="rounded-full border border-border px-3 py-1 font-workspace-mono text-[10px] uppercase tracking-[0.14em] text-text-muted">
              Soon
            </span>
          </article>
        ))}
      </div>
    </section>
  );
}
