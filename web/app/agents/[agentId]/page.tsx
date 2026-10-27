"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  AgentBackLink,
  ChatEmptyState,
  ChatInputBar,
  ChatThread,
  type ChatBubbleMessage,
} from "@/components/workspace/AgentWorkspace";
import {
  type AgentId,
  getAgentById,
  getAgentChatConfig,
} from "@/lib/data/workspace";
import { sendAgentMessage } from "@/lib/api/workspace";
import { MiloCampaigns } from "@/components/workspace/MiloCampaigns";
import { SleyzInbox } from "@/components/workspace/SleyzInbox";
import { VeaVideos } from "@/components/workspace/VeaVideos";
import {useMiloOrg} from '@/lib/hooks/useMiloOrg';

function isAgentId(value: string): value is AgentId {
  return value === "milo" || value === "sleyz" || value === "vea";
}

export default function AgentChatPage() {
  const org=useMiloOrg();return org?<AgentChat key={org} org={org}/>:<p className="p-5 text-sm">Sign in to chat with your agents.</p>;
}
function AgentChat({org}:{org:string}) {
  const params = useParams<{ agentId: string }>();
  const agentId = params.agentId;
  return <AgentConversation key={agentId} org={org} agentId={agentId}/>;
}
function AgentConversation({org,agentId}:{org:string;agentId:string}){
  const [messages, setMessages] = useState<ChatBubbleMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const alive=useRef(false),lock=useRef(false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);

  if (!isAgentId(agentId)) {
    return (
      <div className="flex h-full items-center justify-center bg-white px-6 text-center font-workspace-sans">
        <div>
          <h1 className="font-workspace-display text-2xl font-extrabold text-[#111111]">
            Agent not found
          </h1>
          <Link href="/agents" className="mt-3 inline-flex text-[13px] text-converza-blue">
            Back to agents
          </Link>
        </div>
      </div>
    );
  }

  const activeAgentId: AgentId = agentId;
  const agent = getAgentById(activeAgentId);
  const config = getAgentChatConfig(activeAgentId);

  if (!agent) return null;

  async function sendMessage(text: string) {
    if(lock.current)return;lock.current=true;
    const userMessage: ChatBubbleMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    setMessages((current) => [...current, userMessage]);
    setIsSending(true);

    try {
      const result = await sendAgentMessage(activeAgentId, text,org);
      if(!alive.current)return;
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "agent",
          content:
            result.response ||
            "Queued. I will post the review item in Squad chat when the work is ready.",
        },
      ]);
    } catch (error) {
      if(!alive.current)return;
      const message = error instanceof Error ? error.message : "Agent request failed";
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "agent",
          content: `I could not complete that request.\n\n${message}`,
        },
      ]);
    } finally {
      lock.current=false;if(alive.current)setIsSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-white">
      <AgentBackLink />
      {activeAgentId === "sleyz" && <SleyzInbox />}
      {activeAgentId === "milo" && <MiloCampaigns />}
      {activeAgentId === "vea" && <VeaVideos />}
      {activeAgentId !== "vea" && (messages.length === 0 ? (
        <ChatEmptyState
          eyebrow={config.eyebrow}
          color={agent.color}
          headline={config.headline}
          accentWord={config.accentWord}
          description={config.description}
          suggestions={config.suggestions}
          metrics={config.metrics}
          onSuggestion={sendMessage}
        />
      ) : (
        <ChatThread messages={messages} agentColor={agent.color} />
      ))}
      {activeAgentId !== "vea" && <ChatInputBar
        placeholder={config.placeholder}
        showTaskToggle
        isSending={isSending}
        onSend={sendMessage}
      />}
    </div>
  );
}
