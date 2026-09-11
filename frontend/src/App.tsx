import { useCallback, useEffect, useMemo, useState } from "react";
import {
  addSite,
  fetchArticles,
  fetchScoreStatus,
  fetchSites,
  refreshArticles,
  removeSite,
  summarizeArticle,
  type Article,
  type ArticlesResponse,
  type BoardSite,
  type CategoryCounts,
  type ScoreStatus,
  type UrgencyCounts,
} from "./api";

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50] as const;

const CATEGORY_KEYS = [
  "취약점",
  "랜섬웨어",
  "공급망",
  "국가배후",
  "AI 보안",
  "데이터유출",
  "악성코드",
  "피싱",
  "클라우드",
  "정책·규제",
  "기타",
] as const;

type CategoryKey = (typeof CATEGORY_KEYS)[number];

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  취약점: "취약점",
  랜섬웨어: "랜섬웨어",
  공급망: "공급망",
  국가배후: "국가배후",
  "AI 보안": "AI 보안",
  데이터유출: "데이터유출",
  악성코드: "악성코드",
  피싱: "피싱",
  클라우드: "클라우드",
  "정책·규제": "정책·규제",
  기타: "기타",
};

const CATEGORY_SLUG: Record<CategoryKey, string> = {
  취약점: "vuln",
  랜섬웨어: "ransom",
  공급망: "supply",
  국가배후: "nation",
  "AI 보안": "ai",
  데이터유출: "breach",
  악성코드: "malware",
  피싱: "phish",
  클라우드: "cloud",
  "정책·규제": "policy",
  기타: "other",
};

const CATEGORY_COLORS: Record<CategoryKey, string> = {
  취약점: "#4338ca",
  랜섬웨어: "#be123c",
  공급망: "#c2410c",
  국가배후: "#7e22ce",
  "AI 보안": "#0e7490",
  데이터유출: "#b45309",
  악성코드: "#9f1239",
  피싱: "#a16207",
  클라우드: "#0369a1",
  "정책·규제": "#4b5563",
  기타: "#64748b",
};

const URGENCY_KEYS = ["URGENT", "HIGH", "MEDIUM", "LOW"] as const;
type UrgencyKey = (typeof URGENCY_KEYS)[number];

const URGENCY_LABELS: Record<UrgencyKey, string> = {
  URGENT: "긴급",
  HIGH: "높음",
  MEDIUM: "보통",
  LOW: "낮음",
};

const URGENCY_RANK: Record<string, number> = {
  URGENT: 4,
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
};

const URGENCY_COLORS: Record<UrgencyKey, string> = {
  URGENT: "#ff5d4f",
  HIGH: "#ff8c42",
  MEDIUM: "#e7c73c",
  LOW: "#4d78ff",
};

type SortField = "date" | "title" | "urgency" | "source";
type SortDir = "asc" | "desc";

const SORT_FIELDS: readonly (readonly [SortField, string])[] = [
  ["date", "날짜"],
  ["title", "제목"],
  ["urgency", "긴급도"],
  ["source", "출처"],
] as const;

function formatUpdatedAt(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
  } catch {
    return iso;
  }
}

function formatPublished(value: string): string {
  if (!value) return "—";
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`;
}

function displayTitle(article: Article): string {
  return article.title_translated || article.title;
}

function parseSortDate(value: string): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  return Number.isNaN(ts) ? 0 : ts;
}

function urgencyRank(urgency: string): number {
  return URGENCY_RANK[(urgency || "").toUpperCase()] ?? 0;
}

function emptyCategoryCounts(): CategoryCounts {
  return {
    취약점: 0,
    랜섬웨어: 0,
    공급망: 0,
    국가배후: 0,
    "AI 보안": 0,
    데이터유출: 0,
    악성코드: 0,
    피싱: 0,
    클라우드: 0,
    "정책·규제": 0,
    기타: 0,
  };
}

function articleCategory(article: Article): CategoryKey | "" {
  const raw = (article.category || "").trim();
  if ((CATEGORY_KEYS as readonly string[]).includes(raw)) {
    return raw as CategoryKey;
  }
  return "";
}

function computeUrgencyCounts(articles: Article[]): UrgencyCounts {
  const counts: UrgencyCounts = { URGENT: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
  for (const a of articles) {
    const key = (a.urgency || "").toUpperCase();
    if (key in counts) counts[key as keyof UrgencyCounts] += 1;
  }
  return counts;
}

function computeCategoryCounts(articles: Article[]): CategoryCounts {
  const counts = emptyCategoryCounts();
  for (const a of articles) {
    const cat = articleCategory(a);
    if (cat) counts[cat] += 1;
  }
  return counts;
}

function sortArticles(
  articles: Article[],
  field: SortField,
  dir: SortDir,
): Article[] {
  const sorted = [...articles];
  const sign = dir === "asc" ? 1 : -1;
  sorted.sort((a, b) => {
    let cmp = 0;
    switch (field) {
      case "date":
        cmp = parseSortDate(a.published) - parseSortDate(b.published);
        break;
      case "title":
        cmp = displayTitle(a).localeCompare(displayTitle(b), "ko-KR", {
          sensitivity: "base",
        });
        break;
      case "urgency":
        cmp = urgencyRank(a.urgency) - urgencyRank(b.urgency);
        break;
      case "source":
        cmp = (a.source || "").localeCompare(b.source || "", "ko-KR", {
          sensitivity: "base",
        });
        break;
    }
    if (cmp !== 0) return cmp * sign;
    return displayTitle(a).localeCompare(displayTitle(b), "ko-KR");
  });
  return sorted;
}

function useTheme() {
  const [preference, setPreference] = useState<"light" | "dark" | "system">(() => {
    const saved = localStorage.getItem("board-theme");
    if (saved === "light" || saved === "dark") return saved;
    return "system";
  });
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const theme = preference === "system" ? (systemDark ? "dark" : "light") : preference;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    localStorage.setItem("board-theme", next);
    setPreference(next);
  };

  return { theme, toggle };
}

type ChartSlice = { key: string; label: string; value: number; color: string };

function CountBarChart({
  slices,
  activeKey,
  onSelect,
}: {
  slices: ChartSlice[];
  activeKey: string;
  onSelect: (key: string) => void;
}) {
  const max = Math.max(1, ...slices.map((s) => s.value));
  return (
    <ul className="bar-chart">
      {slices.map((s) => (
        <li key={s.key}>
          <button
            type="button"
            className={`bar-row ${activeKey === s.key ? "active" : ""}`}
            onClick={() => onSelect(s.key)}
          >
            <span className="bar-label">{s.label}</span>
            <span className="bar-track">
              <span
                className="bar-fill"
                style={{
                  width: `${(s.value / max) * 100}%`,
                  background: s.color,
                }}
              />
            </span>
            <span className="bar-value">{s.value}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function CountPieChart({
  slices,
  activeKey,
  onSelect,
}: {
  slices: ChartSlice[];
  activeKey: string;
  onSelect: (key: string) => void;
}) {
  const total = slices.reduce((sum, s) => sum + s.value, 0) || 1;
  const radius = 42;
  const cx = 50;
  const cy = 50;
  let angle = -Math.PI / 2;

  const paths = slices
    .filter((s) => s.value > 0)
    .map((s) => {
      const sweep = (s.value / total) * Math.PI * 2;
      const start = angle;
      angle += sweep;
      const x1 = cx + radius * Math.cos(start);
      const y1 = cy + radius * Math.sin(start);
      const x2 = cx + radius * Math.cos(angle);
      const y2 = cy + radius * Math.sin(angle);
      const large = sweep > Math.PI ? 1 : 0;
      const d =
        sweep >= Math.PI * 2 - 1e-6
          ? `M ${cx} ${cy - radius} A ${radius} ${radius} 0 1 1 ${cx - 0.01} ${cy - radius} Z`
          : `M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z`;
      return { ...s, d };
    });

  return (
    <div className="pie-panel">
      <svg className="pie-svg" viewBox="0 0 100 100" role="img" aria-label="Distribution">
        {paths.length === 0 ? (
          <circle cx={cx} cy={cy} r={radius} fill="var(--border)" />
        ) : (
          paths.map((p) => (
            <path
              key={p.key}
              d={p.d}
              fill={p.color}
              className={`pie-slice ${activeKey === p.key ? "active" : ""}`}
              onClick={() => onSelect(p.key)}
            />
          ))
        )}
      </svg>
      <ul className="pie-legend">
        {slices.map((s) => {
          const pct = Math.round((s.value / total) * 100);
          return (
            <li key={s.key}>
              <button
                type="button"
                className={`legend-btn ${activeKey === s.key ? "active" : ""}`}
                onClick={() => onSelect(s.key)}
              >
                <span className="swatch" style={{ background: s.color }} />
                {s.label}: {pct}%
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function pageNumbers(current: number, total: number): number[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = new Set<number>([1, total, current, current - 1, current + 1]);
  if (current <= 3) {
    pages.add(2);
    pages.add(3);
    pages.add(4);
  }
  if (current >= total - 2) {
    pages.add(total - 1);
    pages.add(total - 2);
    pages.add(total - 3);
  }
  return [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
}

export default function App() {
  const { theme, toggle } = useTheme();
  const [data, setData] = useState<ArticlesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [urgencyFilter, setUrgencyFilter] = useState<string>("ALL");
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [sortField, setSortField] = useState<SortField>(() => {
    const saved = localStorage.getItem("board-sort-field");
    if (saved === "date" || saved === "title" || saved === "urgency" || saved === "source") {
      return saved;
    }
    return "date";
  });
  const [sortDir, setSortDir] = useState<SortDir>(() => {
    const saved = localStorage.getItem("board-sort-dir");
    return saved === "asc" ? "asc" : "desc";
  });
  const [pageSize, setPageSize] = useState<number>(() => {
    const saved = Number(localStorage.getItem("board-page-size"));
    return PAGE_SIZE_OPTIONS.includes(saved as (typeof PAGE_SIZE_OPTIONS)[number])
      ? saved
      : 10;
  });
  const [page, setPage] = useState(1);
  const [summarizingId, setSummarizingId] = useState<string | null>(null);
  const [showTop, setShowTop] = useState(false);
  const [sitesOpen, setSitesOpen] = useState(false);
  const [sites, setSites] = useState<BoardSite[]>([]);
  const [sitesBusy, setSitesBusy] = useState(false);
  const [newFeedUrl, setNewFeedUrl] = useState("");
  const [scoring, setScoring] = useState(false);

  const applyArticlesPayload = useCallback((res: ArticlesResponse) => {
    setData(res);
    if (res.sites) setSites(res.sites);
  }, []);

  const pollScoring = useCallback(async () => {
    setScoring(true);
    const started = Date.now();
    const maxMs = 45 * 60 * 1000; // safety cap
    try {
      while (Date.now() - started < maxMs) {
        await new Promise((r) => setTimeout(r, 2000));
        let status: ScoreStatus;
        try {
          status = await fetchScoreStatus();
        } catch {
          break;
        }
        const total = status.total || 0;
        const done = status.completed || 0;
        if (status.running) {
          setStatusNote(
            total > 0
              ? `Scoring ${done}/${total}… ${status.current_title || ""}`.trim()
              : "Scoring articles…",
          );
        }
        try {
          const latest = await fetchArticles();
          applyArticlesPayload(latest);
        } catch {
          /* keep last good snapshot */
        }
        if (!status.running) {
          const parts = [
            `Scored ${status.ok}/${status.total || done}`,
          ];
          if (status.failed) parts.push(`${status.failed} failed/deferred`);
          if (status.error) parts.push(status.error);
          setStatusNote(parts.join(" · "));
          break;
        }
      }
    } finally {
      setScoring(false);
    }
  }, [applyArticlesPayload]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchArticles();
      applyArticlesPayload(res);
      if (!res.sites) {
        const s = await fetchSites();
        setSites(s.sites);
      }
      setPage(1);
      if (res.scoring?.running) {
        void pollScoring();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [applyArticlesPayload, pollScoring]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    setStatusNote("Fetching site RSS…");
    try {
      const res = await refreshArticles(true);
      applyArticlesPayload(res);
      setPage(1);
      const parts = [`+${res.new_count ?? 0} new`];
      if (res.skipped_duplicates) parts.push(`${res.skipped_duplicates} dupes skipped`);
      if (res.feed_errors) parts.push(`${res.feed_errors} feed error(s)`);
      if (res.pruned_count) parts.push(`${res.pruned_count} pruned`);
      const willScore = Boolean(res.scoring_started || res.scoring?.running);
      if (willScore) {
        setStatusNote(
          res.scoring_started
            ? `${parts.join(" · ")} · scoring started…`
            : `${parts.join(" · ")} · scoring in progress…`,
        );
        setRefreshing(false);
        await pollScoring();
      } else {
        setStatusNote(parts.join(" · ") || "RSS updated");
        setRefreshing(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatusNote(null);
      setRefreshing(false);
    }
  }, [applyArticlesPayload, pollScoring]);

  const onAddSite = useCallback(async () => {
    const feedUrl = newFeedUrl.trim();
    if (!feedUrl) {
      setError("RSS feed URL is required.");
      return;
    }
    setSitesBusy(true);
    setError(null);
    try {
      const res = await addSite(feedUrl);
      if (res.site) {
        setSites((prev) => {
          const rest = prev.filter((s) => s.domain !== res.site!.domain);
          return [...rest, res.site!].sort((a, b) => a.domain.localeCompare(b.domain));
        });
      } else {
        const s = await fetchSites();
        setSites(s.sites);
      }
      applyArticlesPayload(res.articles);
      setNewFeedUrl("");
      setStatusNote(
        `Added ${res.site?.domain ?? "site"} to whitelist · click ↻ to fetch articles`,
      );
      setPage(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSitesBusy(false);
    }
  }, [applyArticlesPayload, newFeedUrl]);

  const onRemoveSite = useCallback(
    async (domain: string) => {
      setSitesBusy(true);
      setError(null);
      try {
        const res = await removeSite(domain);
        setSites((prev) => prev.filter((s) => s.domain !== res.removed));
        applyArticlesPayload(res.articles);
        setStatusNote(
          `Removed ${res.removed} · ${res.articles_removed ?? 0} articles dropped`,
        );
        setPage(1);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSitesBusy(false);
      }
    },
    [applyArticlesPayload],
  );

  const onSummarizeOne = useCallback(async (id: string) => {
    setSummarizingId(id);
    setError(null);
    try {
      const updated = await summarizeArticle(id);
      setData((prev) => {
        if (!prev) return prev;
        const articles = prev.articles.map((a) => (a.id === id ? { ...a, ...updated } : a));
        return {
          ...prev,
          articles,
          urgency_counts: computeUrgencyCounts(articles),
          category_counts: computeCategoryCounts(articles),
        };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSummarizingId(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onScroll = () => setShowTop(window.scrollY > 400);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const counts: UrgencyCounts = data?.urgency_counts ?? {
    URGENT: 0,
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
  };
  const catCounts: CategoryCounts = data?.category_counts ?? emptyCategoryCounts();

  const filtered = useMemo(() => {
    const articles = data?.articles ?? [];
    const q = query.trim().toLowerCase();
    return articles.filter((a) => {
      if (urgencyFilter !== "ALL") {
        if ((a.urgency || "").toUpperCase() !== urgencyFilter) return false;
      }
      if (categoryFilter !== "ALL") {
        if (articleCategory(a) !== categoryFilter) return false;
      }
      if (!q) return true;
      const hay = [
        a.title,
        a.title_translated,
        a.source,
        a.summary,
        a.urgency_reason,
        a.category,
        a.link,
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, query, urgencyFilter, categoryFilter]);

  const sorted = useMemo(
    () => sortArticles(filtered, sortField, sortDir),
    [filtered, sortField, sortDir],
  );

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageItems = sorted.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  const pages = pageNumbers(currentPage, pageCount);

  const urgencySlices: ChartSlice[] = URGENCY_KEYS.map((key) => ({
    key,
    label: URGENCY_LABELS[key],
    value: counts[key],
    color: URGENCY_COLORS[key],
  }));

  const categoryChips = CATEGORY_KEYS.map((key) => ({
    key,
    label: CATEGORY_LABELS[key],
    value: catCounts[key],
    color: CATEGORY_COLORS[key],
  }));

  const onUrgencySelect = (key: string) => {
    setUrgencyFilter((prev) => (prev === key ? "ALL" : key));
    setPage(1);
  };

  const onCategorySelect = (key: string) => {
    setCategoryFilter((prev) => (prev === key ? "ALL" : key));
    setPage(1);
  };

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo-mark">C/</span>
          <h1 className="logo-text">Cybersecurity News Report</h1>
        </div>
        <div className="header-right">
          <p className="refresh-stamp">
            last refresh {formatUpdatedAt(data?.updated_at ?? "")}
          </p>
          <div className="header-actions">
            <button
              type="button"
              className="icon-btn primary"
              title="Refresh + score new"
              aria-label="Refresh and score new"
              disabled={refreshing || scoring || loading}
              onClick={() => void onRefresh()}
            >
              {refreshing ? "…" : "↻"}
            </button>
            <button
              type="button"
              className="icon-btn"
              title={theme === "dark" ? "Light mode" : "Dark mode"}
              aria-label="Toggle theme"
              onClick={toggle}
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
            <button
              type="button"
              className={`icon-btn ${sitesOpen ? "active" : ""}`}
              title="Sources"
              aria-label="Manage whitelist sources"
              aria-expanded={sitesOpen}
              onClick={() => setSitesOpen((v) => !v)}
            >
              ⊕
            </button>
          </div>
        </div>
      </header>

      <div className="page">
      {sitesOpen && (
        <section className="dash-card sites-card" aria-label="Whitelist sources">
          <div className="sites-title-row">
            <span className="sites-title">Sources</span>
            <span className="sites-sub">
              RSS whitelist · last {data?.article_max_age_days ?? 3} days
            </span>
          </div>
          <ul className="sites-list">
            {sites.map((site) => (
              <li key={site.domain} className={`site-row ${site.ok ? "" : "bad"}`}>
                <div className="site-main">
                  <span className="site-domain">{site.domain}</span>
                  <a
                    className="site-feed"
                    href={site.feed_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {site.feed_url}
                  </a>
                  {!site.ok && (
                    <span className="site-status err" title={site.error}>
                      Broken: {site.error || "feed error"}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className="site-x"
                  title={`Remove ${site.domain}`}
                  aria-label={`Remove ${site.domain}`}
                  disabled={sitesBusy}
                  onClick={() => void onRemoveSite(site.domain)}
                >
                  ×
                </button>
              </li>
            ))}
            {sites.length === 0 && (
              <li className="empty">No sources yet. Paste an RSS URL below.</li>
            )}
          </ul>
          <form
            className="sites-add"
            onSubmit={(e) => {
              e.preventDefault();
              void onAddSite();
            }}
          >
            <input
              type="url"
              placeholder="https://example.com/feed/"
              value={newFeedUrl}
              onChange={(e) => setNewFeedUrl(e.target.value)}
              disabled={sitesBusy}
            />
            <button type="submit" className="btn small" disabled={sitesBusy}>
              {sitesBusy ? "…" : "Add"}
            </button>
          </form>
        </section>
      )}

      <div className="section-head">
        <div className="section-head-left">
          <div>
            <p className="section-eyebrow">Threat Overview</p>
            <h2 className="section-title">위협 분포</h2>
          </div>
        </div>
      </div>

      <section className="dash-card">
        <div className="charts">
          <CountBarChart
            slices={urgencySlices}
            activeKey={urgencyFilter}
            onSelect={onUrgencySelect}
          />
          <CountPieChart
            slices={urgencySlices}
            activeKey={urgencyFilter}
            onSelect={onUrgencySelect}
          />
        </div>
        <p className="chart-total">
          <span className="chart-total-label">Total</span>
          <span className="chart-total-value">{data?.count ?? 0}</span>
        </p>
      </section>

      <div className="section-head">
        <div className="section-head-left">
          <div>
            <p className="section-eyebrow">Curated News Feed</p>
            <h2 className="section-title">뉴스 브리핑</h2>
          </div>
        </div>
        <span className="section-meta">{sorted.length}건</span>
      </div>

      <div className="toolbar">
        <input
          className="search"
          type="search"
          placeholder="Search title, summary, source…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
        <div className="sort-bar">
          <div className="sort-left">
            <span className="sort-label">정렬</span>
            {SORT_FIELDS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`chip ${sortField === value ? "active" : ""}`}
                onClick={() => {
                  setSortField(value);
                  localStorage.setItem("board-sort-field", value);
                  setPage(1);
                }}
              >
                {label}
              </button>
            ))}
            <button
              type="button"
              className={`chip dir-btn ${sortDir}`}
              aria-label="정렬 방향 전환"
              onClick={() => {
                const next = sortDir === "asc" ? "desc" : "asc";
                setSortDir(next);
                localStorage.setItem("board-sort-dir", next);
                setPage(1);
              }}
            >
              {sortDir === "asc" ? "↑ 오름차순" : "↓ 내림차순"}
            </button>
          </div>
          <div className="sort-right">
            <span className="toolbar-meta">
              {pageItems.length}/{sorted.length}
            </span>
            <label className="page-size">
              <select
                value={pageSize}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  setPageSize(next);
                  localStorage.setItem("board-page-size", String(next));
                  setPage(1);
                }}
              >
                {PAGE_SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              개씩
            </label>
          </div>
        </div>

        <div className="filter-row">
          <span className="sort-label">주제</span>
          <div className="cat-chips" role="list" aria-label="Category filters">
            <button
              type="button"
              role="listitem"
              className={`chip cat-chip ${categoryFilter === "ALL" ? "active" : ""}`}
              onClick={() => onCategorySelect("ALL")}
            >
              <span className="cat-chip-label">전체</span>
              <span className="cat-chip-count">{data?.count ?? 0}</span>
            </button>
            {categoryChips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                role="listitem"
                className={`chip cat-chip ${categoryFilter === chip.key ? "active" : ""}`}
                style={{ ["--chip-color" as string]: chip.color }}
                onClick={() => onCategorySelect(chip.key)}
              >
                <span className="cat-chip-dot" />
                <span className="cat-chip-label">{chip.label}</span>
                <span className="cat-chip-count">{chip.value}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {statusNote && <div className="note">{statusNote}</div>}
      {error && <div className="error">{error}</div>}
      {loading && <p className="status">Loading articles…</p>}

      {!loading && !error && (
        <ul className="list">
          {pageItems.map((article) => (
            <ArticleRow
              key={article.id}
              article={article}
              busy={summarizingId === article.id}
              onSummarize={() => void onSummarizeOne(article.id)}
            />
          ))}
          {pageItems.length === 0 && (
            <li className="empty">No articles match your filters.</li>
          )}
        </ul>
      )}

      {!loading && pageCount > 1 && (
        <div className="pager">
          <button
            type="button"
            className="btn secondary"
            disabled={currentPage <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <div className="page-list">
            {pages.map((p, i) => {
              const prev = pages[i - 1];
              const showGap = prev != null && p - prev > 1;
              return (
                <span key={p} className="page-slot">
                  {showGap && <span className="ellipsis">…</span>}
                  <button
                    type="button"
                    className={`page-btn ${p === currentPage ? "active" : ""}`}
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </button>
                </span>
              );
            })}
          </div>
          <button
            type="button"
            className="btn secondary"
            disabled={currentPage >= pageCount}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      )}
      </div>

      {showTop && (
        <button
          type="button"
          className="to-top"
          aria-label="Back to top"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
        >
          ↑
        </button>
      )}
    </>
  );
}

function ArticleRow({
  article,
  busy,
  onSummarize,
}: {
  article: Article;
  busy: boolean;
  onSummarize: () => void;
}) {
  const urgency = (article.urgency || "").toUpperCase();
  const category = articleCategory(article);
  const translated = (article.title_translated || "").trim();
  const original = (article.title || "").trim();
  const showOriginal = Boolean(translated) && Boolean(original) && translated !== original;
  const scored =
    Boolean(urgency) &&
    Boolean(article.summary) &&
    !article.summary.startsWith("(Could not summarize:") &&
    article.summary !== "(cancelled)";

  return (
    <li className="card">
      <div className="card-head">
        <div className="card-badges">
          {urgency && (
            <span className={`badge ${urgency.toLowerCase()}`}>
              {URGENCY_LABELS[urgency as UrgencyKey] ?? urgency}
            </span>
          )}
          {category && (
            <span
              className={`badge cat cat-${CATEGORY_SLUG[category]}`}
              style={{ ["--cat-color" as string]: CATEGORY_COLORS[category] }}
            >
              {category}
            </span>
          )}
        </div>
        <time className="card-date" dateTime={article.published}>
          {formatPublished(article.published)}
        </time>
      </div>

      <a className="card-title" href={article.link} target="_blank" rel="noreferrer">
        {displayTitle(article)}
      </a>
      {showOriginal && <div className="original">{original}</div>}
      {article.source && <div className="card-source">{article.source}</div>}

      {(article.urgency_reason || scored) && (
        <div className="insight">
          {article.urgency_reason && (
            <div className="insight-row">
              <span className="insight-label">판단</span>
              <p>{article.urgency_reason}</p>
            </div>
          )}
          {scored && (
            <div className="insight-row">
              <span className="insight-label accent">요약</span>
              <p>{article.summary}</p>
            </div>
          )}
        </div>
      )}

      <div className="card-foot">
        {!scored ? (
          <button
            type="button"
            className="btn secondary small"
            disabled={busy}
            onClick={onSummarize}
          >
            {busy ? "Scoring…" : "Score now"}
          </button>
        ) : (
          <span />
        )}
        <a className="ext-link" href={article.link} target="_blank" rel="noreferrer">
          원문 확인
          <span aria-hidden="true">↗</span>
        </a>
      </div>
    </li>
  );
}
