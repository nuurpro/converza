import type {SleyzDraftArtifact} from './sleyz';
import type {VeaVideoArtifact} from './vea';

export type AgentId = 'milo' | 'sleyz' | 'vea';
export interface WorkspaceAgent {
  id: AgentId | string; name: string; role: string; roleLabel: string;
  color: string; dimColor: string; voice: string; statusLabel: string; metricText: string;
}
export interface DashboardStat {value: string; label: string;}
export interface ActivityFeedItem {id: string; agentId?: AgentId; color: string; text: string; timestamp: string;}
export interface ChatMetric {value: string; label: string;}
export interface AgentChatConfig {
  agentId: AgentId; eyebrow: string; headline: string; accentWord: string;
  description: string; placeholder: string; suggestions: string[]; metrics: ChatMetric[];
}
export type MessageRole = 'user' | 'assistant' | 'human_edit';
export type DraftStatus = 'pending' | 'approved' | 'edited' | 'rejected' | 'published' | 'generating';
export interface HitlCardData {
  id: string; label: string; content: string; status: DraftStatus; revision?: number;
  deliveryStatus?: string; deliveryError?: string | null; generationError?: string | null;
  resolvedAt?: string | null; canResolve?: boolean; canDeliver?: boolean; canRefresh?: boolean;
  artifact?: SleyzDraftArtifact | null; veaArtifact?: VeaVideoArtifact | null; simulated?: boolean;
  supersededBy?: string | null; learningStatus?: string | null; learningError?: string | null;
}
export interface SquadMessageData {
  id: string; role: MessageRole; sender: 'Converza' | 'Milo' | 'Sleyz' | 'Vea' | 'Owner';
  senderColor: string; mark: string; timestamp: string; text: string; hitlCard?: HitlCardData;
}
export interface WorkspaceNavItem {
  id: 'dashboard' | 'agents' | 'squad' | 'products' | 'channels' | 'settings';
  label: string; href: string; badge?: string; placement: 'main' | 'footer';
}
export const workspaceTokens = {
  blue:'#0070F3', milo:'#D97706', miloDim:'rgba(217,119,6,0.1)',
  sleyz:'#16A34A', sleyzDim:'rgba(22,163,74,0.1)', vea:'#7C3AED', veaDim:'rgba(124,58,237,0.1)', black:'#000000',
};
const agents: WorkspaceAgent[] = [
  {id:'milo',name:'Milo',role:'Marketing',roleLabel:'Marketing',color:workspaceTokens.milo,dimColor:workspaceTokens.miloDim,voice:'Confident, trend-aware, strategic',statusLabel:'Active',metricText:''},
  {id:'sleyz',name:'Sleyz',role:'Sales',roleLabel:'Sales',color:workspaceTokens.sleyz,dimColor:workspaceTokens.sleyzDim,voice:'Direct, warm, closer energy',statusLabel:'Active',metricText:''},
  {id:'vea',name:'Vea',role:'Video',roleLabel:'Video',color:workspaceTokens.vea,dimColor:workspaceTokens.veaDim,voice:'Concise, technical, craft-focused',statusLabel:'Active',metricText:''},
];
const soonAgents: WorkspaceAgent[] = [
  {id:'bao',name:'Bao',role:'Supply Chain & Purchasing Buyer',roleLabel:'Supply chain',color:'#111111',dimColor:'rgba(0,0,0,0.06)',voice:'Practical, vendor-aware, margin-focused',statusLabel:'Soon',metricText:'Purchasing, supplier follow-ups, inventory timing'},
  {id:'clara',name:'Clara',role:'Revenue Recovery & Support Lead',roleLabel:'Recovery support',color:'#111111',dimColor:'rgba(0,0,0,0.06)',voice:'Calm, helpful, retention-focused',statusLabel:'Soon',metricText:'Failed payments, refunds, support recovery'},
  {id:'arthur',name:'Arthur',role:'Pricing & Competitor Analyst',roleLabel:'Pricing analyst',color:'#111111',dimColor:'rgba(0,0,0,0.06)',voice:'Precise, analytical, market-aware',statusLabel:'Soon',metricText:'Pricing tests, competitor shifts, margin alerts'},
];
const agentChatConfigs: Record<AgentId, AgentChatConfig> = {
  milo:{agentId:'milo',eyebrow:'Milo · Marketing',headline:'What are we shipping',accentWord:'today?',description:'Evidence-backed hooks, campaign angles, scripts and captions.',placeholder:'Reply to Milo...',suggestions:[
    'Suggest three campaign angles from our buyer objections.', 'Draft a product campaign using our Brand Passport.',
    'Which claims need more supporting evidence?', 'Write a hook for a video ad targeting cold audiences.',
  ],metrics:[]},
  sleyz:{agentId:'sleyz',eyebrow:'Sleyz · Sales',headline:'Who do we close',accentWord:'today?',description:'Buyer questions, objections and replies for your review.',placeholder:'Reply to Sleyz...',suggestions:[
    'Draft a reply to a buyer asking about price.', 'Help answer an objection about product quality.',
    'Draft a follow-up for a customer who went cold.', 'What product facts are missing from our catalog?',
  ],metrics:[]},
  vea:{agentId:'vea',eyebrow:'Vea · Video',headline:'What are we cutting',accentWord:'today?',description:'Approved scripts, renders and video variants.',placeholder:'Reply to Vea...',suggestions:[
    "Render an approved Milo script.", 'Review video variants.', 'Check the latest render status.', 'Review clips before exporting.',
  ],metrics:[]},
};
const workspaceNavItems: WorkspaceNavItem[] = [
  {id:'dashboard',label:'Dashboard',href:'/',placement:'main'},
  {id:'agents',label:'Agents',href:'/agents',placement:'main'},
  {id:'squad',label:'Squad chat',href:'/squad',placement:'main'},
  {id:'products',label:'Products',href:'/products',placement:'main'},
  {id:'channels',label:'Connect channels',href:'/connect-channels',placement:'main'},
  {id:'settings',label:'Settings',href:'/settings',placement:'footer'},
];
export function getAgents() {return agents;}
export function getSoonAgents() {return soonAgents;}
export function getAgentById(id: string) {return agents.find(agent=>agent.id===id);}
export function getAgentChatConfig(id: AgentId) {return agentChatConfigs[id];}
export function getWorkspaceNavItems() {return workspaceNavItems;}
