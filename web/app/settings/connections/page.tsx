"use client";

import { useState } from "react";
import {
  BarChart3,
  CreditCard,
  Globe2,
  Instagram,
  Mail,
  Megaphone,
  MessageCircle,
  MessagesSquare,
  Search,
  Send,
  ShoppingBag,
  Video,
} from "lucide-react";

const channels = [
  { name: "Telegram", icon: Send },
  { name: "Instagram DM", icon: Instagram },
  { name: "TikTok", icon: Video },
  { name: "WhatsApp", icon: MessageCircle },
  { name: "Website chat", icon: Globe2 },
];

const integrations = [
  { name: "Shopify", note: "Catalog, orders, and customer events", icon: ShoppingBag },
  { name: "Meta Ads", note: "Campaign performance and audiences", icon: Megaphone },
  { name: "TikTok Ads", note: "Campaign and creative performance", icon: Video },
  { name: "GA4", note: "Website analytics and attribution", icon: BarChart3 },
  { name: "Klaviyo", note: "Email and SMS lifecycle data", icon: Mail },
  { name: "Stripe", note: "Revenue, payments, and refunds", icon: CreditCard },
  { name: "Slack", note: "Notifications and approval updates", icon: MessagesSquare },
  { name: "Google Ads", note: "Search and Performance Max campaigns", icon: Search },
];

export default function ConnectionsSettingsPage() {
  const [unavailableIntegration, setUnavailableIntegration] = useState<string | null>(null);

  return (
    <div className="space-y-12">
      <header>
        <h2 className="text-[28px] font-medium tracking-[-0.025em] text-text-primary">
          Connections
        </h2>
        <p className="mt-2 max-w-lg text-[15px] leading-relaxed text-text-secondary">
          Manage the channels where customers reach you and the data sources your workspace reads.
        </p>
      </header>

      <section aria-labelledby="communication-channels-heading">
        <div className="mb-4">
          <h3
            id="communication-channels-heading"
            className="text-[16px] font-medium text-text-primary"
          >
            Communication Channels
          </h3>
          <p className="mt-1 text-[13px] leading-relaxed text-text-muted">
            Customer conversations and website messaging.
          </p>
        </div>

        <div className="overflow-hidden rounded-lg border border-border bg-bg-elevated">
          {channels.map((channel) => (
            <div
              key={channel.name}
              className="flex min-h-16 items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-bg-secondary text-text-secondary">
                <channel.icon size={16} strokeWidth={1.8} aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1 text-[14px] font-medium text-text-primary">
                {channel.name}
              </span>
              <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
                Coming soon
              </span>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="data-integrations-heading">
        <div className="mb-4">
          <h3 id="data-integrations-heading" className="text-[16px] font-medium text-text-primary">
            Data Integrations
          </h3>
          <p className="mt-1 text-[13px] leading-relaxed text-text-muted">
            Commerce, marketing, analytics, and team data.
          </p>
        </div>

        <div className="overflow-hidden rounded-lg border border-border bg-bg-elevated">
          {integrations.map((integration) => {
            const showNotice = unavailableIntegration === integration.name;

            return (
              <div
                key={integration.name}
                className="flex min-h-20 items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-bg-secondary text-text-secondary">
                  <integration.icon size={16} strokeWidth={1.8} aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium text-text-primary">{integration.name}</div>
                  <div className="mt-0.5 text-[12.5px] leading-snug text-text-muted">
                    {integration.note}
                  </div>
                  {showNotice && (
                    <p
                      id="connector-unavailable-notice"
                      className="mt-1.5 text-[12px] text-text-secondary"
                      role="status"
                    >
                      This connector is not available yet.
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setUnavailableIntegration(integration.name)}
                  aria-label={`Connect ${integration.name}`}
                  aria-describedby={showNotice ? "connector-unavailable-notice" : undefined}
                  className="shrink-0 rounded-full border border-border bg-bg-primary px-4 py-1.5 text-[12px] font-medium text-text-primary transition-colors hover:border-border-hover hover:bg-bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-text-primary/20"
                >
                  Connect
                </button>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
