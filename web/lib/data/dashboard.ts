import type {MiloCampaign} from './milo';

export function pendingCampaignReviews(campaigns: MiloCampaign[]) {
  return campaigns.filter(campaign=>campaign.script_status==='pending' && ['awaiting_review','blocked','needs_evidence'].includes(campaign.status))
    .map(campaign=>({...campaign,href:`/agents/milo#campaign-${encodeURIComponent(campaign.id)}`}));
}
