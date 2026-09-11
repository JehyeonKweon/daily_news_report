export type Article = {
  id: string;
  title: string;
  link: string;
  source: string;
  published: string;
  topic: string;
  title_translated: string;
  summary: string;
  relevance?: string;
  category: string;
  urgency: string;
  urgency_reason: string;
  first_seen?: string;
  last_seen?: string;
  summarized_at?: string;
};

export type UrgencyCounts = {
  URGENT: number;
  HIGH: number;
  MEDIUM: number;
  LOW: number;
};

export type CategoryCounts = {
  취약점: number;
  랜섬웨어: number;
  공급망: number;
  국가배후: number;
  "AI 보안": number;
  데이터유출: number;
  악성코드: number;
  피싱: number;
  클라우드: number;
  "정책·규제": number;
  기타: number;
};

export type BoardSite = {
  domain: string;
  feed_url: string;
  ok: boolean;
  error: string;
  last_checked: string;
  entry_count: number;
};

export type ScoreStatus = {
  running: boolean;
  total: number;
  completed: number;
  ok: number;
  failed: number;
  current_title: string;
  error: string;
};

export type ArticlesResponse = {
  updated_at: string;
  rss_url: string;
  topic_url?: string;
  count: number;
  new_count?: number;
  summarized_count?: number;
  skipped_summary?: number;
  skipped_duplicates?: number;
  feed_errors?: number;
  pruned_count?: number;
  decoded_urls?: number;
  retention_days?: number;
  article_max_age_days?: number;
  urgency_counts?: UrgencyCounts;
  category_counts?: CategoryCounts;
  articles: Article[];
  sites?: BoardSite[];
  scoring?: ScoreStatus;
  scoring_started?: boolean;
};

export type SitesResponse = {
  count: number;
  sites: BoardSite[];
};

export type SiteMutationResponse = {
  site?: BoardSite;
  new_count?: number;
  removed?: string;
  articles_removed?: number;
  articles: ArticlesResponse;
};

const API_BASE = "";

/** `vite build --mode static` (GitHub Pages): read-only, reads a published JSON snapshot. */
export const STATIC_MODE = import.meta.env.MODE === "static";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const body = JSON.parse(text) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* keep text */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function fetchArticles(): Promise<ArticlesResponse> {
  if (STATIC_MODE) {
    return request<ArticlesResponse>(`./api/articles.json?t=${Date.now()}`);
  }
  return request<ArticlesResponse>("/api/articles");
}

export function fetchScoreStatus(): Promise<ScoreStatus> {
  return request<ScoreStatus>("/api/score-status");
}

export function refreshArticles(summarize = true): Promise<ArticlesResponse> {
  const q = summarize ? "?summarize=true" : "?summarize=false";
  return request<ArticlesResponse>(`/api/articles/refresh${q}`, { method: "POST" });
}

export function summarizeArticle(id: string): Promise<Article> {
  return request<Article>(`/api/articles/${encodeURIComponent(id)}/summarize`, {
    method: "POST",
  });
}

export function fetchSites(): Promise<SitesResponse> {
  return request<SitesResponse>("/api/sites");
}

export function addSite(feed_url: string, domain = ""): Promise<SiteMutationResponse> {
  return request<SiteMutationResponse>("/api/sites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feed_url, domain }),
  });
}

export function removeSite(domain: string): Promise<SiteMutationResponse> {
  return request<SiteMutationResponse>(`/api/sites/${encodeURIComponent(domain)}`, {
    method: "DELETE",
  });
}
