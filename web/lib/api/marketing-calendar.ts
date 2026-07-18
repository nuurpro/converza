import { authHeaders } from "@/lib/api/session";
import { getCurrentOrgId } from "@/lib/org";

export type CalendarDayStatus =
  | "skeleton"
  | "draft"
  | "rendering"
  | "awaiting_hitl"
  | "completed"
  | "failed";

export interface MarketingCalendarDay {
  day_number: number;
  theme: string;
  status: CalendarDayStatus;
  script?: string | null;
  video_url?: string | null;
  hitl_draft_id?: string | null;
  agent_run_id?: string | null;
  render_error?: string | null;
  created_at?: string | null;
  approved_at?: string | null;
  completed_at?: string | null;
}

export interface MarketingCalendar {
  id: string;
  org_id: string;
  duration_days: 14 | 30;
  platforms: string[];
  hours_per_week: number;
  target_video_count: number;
  days: MarketingCalendarDay[];
  created_at?: string;
  updated_at?: string;
}

export interface CalendarInterviewAnswers {
  target_audience: string;
  tone: string[];
  core_offer: string;
  platforms: string[];
  hours_per_week: number;
  duration_days: 14 | 30;
  has_tracked_metrics_before: boolean;
  current_process: string;
  overrode_platform_limit: boolean;
}

function backendPath(path: string) {
  return `/api/backend${path}`;
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await authHeaders({
    "Content-Type": "application/json",
    ...(init?.headers ?? {}),
  });
  const response = await fetch(backendPath(path), { ...init, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = payload?.detail;
    if (typeof detail === "object" && detail?.message) {
      throw new Error(detail.message);
    }
    throw new Error(typeof detail === "string" ? detail : `Request failed with ${response.status}`);
  }
  return payload as T;
}

export async function fetchMarketingCalendar(orgId = getCurrentOrgId()) {
  const payload = await apiJson<{ calendar: MarketingCalendar | null }>(`/api/marketing-calendar/${orgId}`);
  return payload.calendar;
}

export async function createMarketingCalendar(
  answers: CalendarInterviewAnswers,
  orgId = getCurrentOrgId(),
) {
  const payload = await apiJson<{ calendar: MarketingCalendar }>("/api/marketing-calendar/interview", {
    method: "POST",
    body: JSON.stringify({ org_id: orgId, ...answers }),
  });
  return payload.calendar;
}

export async function generateCalendarDayDetail(
  calendarId: string,
  dayNumber: number,
  orgId = getCurrentOrgId(),
) {
  const payload = await apiJson<{ calendar: MarketingCalendar; day: MarketingCalendarDay }>(
    `/api/marketing-calendar/${calendarId}/days/${dayNumber}/detail`,
    { method: "POST", body: JSON.stringify({ org_id: orgId }) },
  );
  return payload;
}

export async function approveCalendarDay(
  calendarId: string,
  dayNumber: number,
  orgId = getCurrentOrgId(),
) {
  const payload = await apiJson<{ calendar: MarketingCalendar; day: MarketingCalendarDay }>(
    `/api/marketing-calendar/${calendarId}/days/${dayNumber}/approve`,
    { method: "POST", body: JSON.stringify({ org_id: orgId }) },
  );
  return payload;
}
