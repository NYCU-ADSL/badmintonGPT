import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight, ClipboardCheck, Loader2, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { QuestionNavigator } from "./QuestionNavigator";
import { LANGUAGE_KEY } from "./i18n";
import { MarkdownText } from "@/components/MarkdownText";
import { toMediaAttachment } from "@/lib/media";
import { AttachmentTile, MediaPlaybackProvider } from "@/components/AttachmentTile";
import type { UIMediaAttachment } from "@/lib/types";

type Rating = { q1: string | null; q2: string | null; updated_at?: string };
type OutputMessage = { text: string; media_urls: {url: string; name?: string}[] };
type Item = { id: string; query_en: string; query_zh_tw: string; answer: string; media: UIMediaAttachment[]; output_messages?: OutputMessage[]; playback_sources?: Record<string, string> };
type Dataset = { id: string; model: string; target_count: number; items: Item[] };
type RatingResult = { ratings: (Rating & { item_id: string })[] };
const EMPTY: Rating = { q1: null, q2: null };
const CODE_KEY = "badmintongpt-evaluator-code";
export const isComplete = (r?: Rating) => !!r && (r.q1 === "unrealistic" ||
  (["realistic", "somewhat_realistic"].includes(r.q1 ?? "") && !!r.q2));

const q1Options = ["realistic", "somewhat_realistic", "unrealistic"];
const q2Options = ["fully_addresses", "partially_addresses", "does_not_address"];
const REQUEST_ERROR = "requestError";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init).catch(() => { throw new Error(REQUEST_ERROR); });
  if (!response.ok) {
    const key = response.status === 409 ? "datasetChanged"
      : response.status === 404 ? "questionMissing"
      : response.status === 503 && url === "/api/dataset" ? "datasetPreparing"
      : response.status === 422 && !init?.method ? "invalidCode" : REQUEST_ERROR;
    throw new Error(key);
  }
  return response.json().catch(() => { throw new Error(REQUEST_ERROR); });
}

function storedCode() { try { return localStorage.getItem(CODE_KEY) ?? ""; } catch { return ""; } }

function Choices({ name, options, value, onChange, disabled }: {
  name: string; options: string[]; value: string | null; onChange: (value: string) => void; disabled: boolean;
}) {
  const { t } = useTranslation("evaluation");
  return <div className="choices">{options.map(id =>
    <label className={`choice ${value === id ? "selected" : ""}`} key={id}>
      <input type="radio" name={name} value={id} checked={value === id} onChange={() => onChange(id)} disabled={disabled} />
      <span><strong>{t(id)}</strong><span className="criterion">{t(`${id}Description`)}</span></span>
      {value === id && <Check size={17} className="choice-check" />}
    </label>)}</div>;
}

export default function App() {
  const { t, i18n } = useTranslation("evaluation");
  const [data, setData] = useState<Dataset | null>(null);
  const [code, setCode] = useState(storedCode);
  const [inputCode, setInputCode] = useState(storedCode);
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  const [drafts, setDrafts] = useState<Record<string, Rating>>({});
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const saveLock = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setNotice("");
    request<Dataset>("/api/dataset").then(async dataset => {
      const result = code ? await request<RatingResult>(`/api/evaluators/${encodeURIComponent(code)}/ratings`) : { ratings: [] };
      if (cancelled) return;
      const saved = Object.fromEntries(result.ratings.map(r => [r.item_id, r]));
      setData(dataset); setRatings(saved); setDrafts({});
      const next = dataset.items.findIndex(i => !isComplete(saved[i.id]));
      setIndex(next < 0 ? 0 : next);
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : REQUEST_ERROR); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code, reload]);

  const hasUnsaved = Object.entries(drafts).some(([id, draft]) =>
    draft.q1 !== (ratings[id]?.q1 ?? null) || draft.q2 !== (ratings[id]?.q2 ?? null));
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (hasUnsaved) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsaved]);

  function login(e: FormEvent) {
    e.preventDefault();
    const next = inputCode.trim();
    if (!/^[A-Za-z0-9_-]{3,64}$/.test(next)) { setError("invalidCode"); return; }
    try { localStorage.setItem(CODE_KEY, next); } catch { /* server still stores ratings */ }
    setCode(next);
  }

  const item = data?.items[index];
  const current = item ? drafts[item.id] ?? ratings[item.id] ?? EMPTY : EMPTY;
  const saved = item ? ratings[item.id] ?? EMPTY : EMPTY;
  const dirty = current.q1 !== saved.q1 || current.q2 !== saved.q2;
  const count = data?.items.filter(i => isComplete(ratings[i.id])).length ?? 0;
  const total = data?.items.length ?? 0;
  const showAnswer = current.q1 === "realistic" || current.q1 === "somewhat_realistic";
  function update(value: Partial<Rating>) {
    if (!item) return;
    setDrafts(d => ({ ...d, [item.id]: { ...current, ...value } }));
    setNotice(""); setError("");
  }
  function navigate(next: number) { setIndex(next); setNotice(""); setError(""); window.scrollTo({ top: 0, behavior: "smooth" }); }
  async function save(next = false) {
    if (!item || !data || saveLock.current) return;
    saveLock.current = true; setSaving(true); setError(""); setNotice("");
    try {
      const result = await request<Rating>(`/api/datasets/${encodeURIComponent(data.id)}/evaluators/${encodeURIComponent(code)}/ratings/${item.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q1: current.q1, q2: current.q2 }),
      });
      setRatings(r => ({ ...r, [item.id]: result }));
      setDrafts(d => { const copy = { ...d }; delete copy[item.id]; return copy; });
      setNotice("savedToServer");
      if (next && index < total - 1) navigate(index + 1);
    } catch (e) { setError(e instanceof Error ? e.message : REQUEST_ERROR); }
    finally { saveLock.current = false; setSaving(false); }
  }

  return <div className="evaluation-app">
    <header className="topbar"><div className="brandmark"><span className="logo"><ClipboardCheck size={22} /></span>
      <div><strong>BadmintonGPT</strong><span>{t("evaluation")}</span></div></div>
      <div className="header-actions"><span className="pilot-badge">{t("pilot", { count: data?.target_count ?? 10 })}</span><label className="language-select" htmlFor="language">{t("language")}
        <select id="language" value={i18n.resolvedLanguage ?? "zh-TW"} onChange={e => {
          const language = e.target.value;
          void i18n.changeLanguage(language);
          try { localStorage.setItem(LANGUAGE_KEY, language); } catch { /* optional preference */ }
        }}><option value="zh-TW" lang="zh-Hant">繁體中文</option><option value="en" lang="en">English</option></select>
      </label></div></header>
    <main className="page-shell">
      <div className="intro"><span className="eyebrow">{t("tagline")}</span><h1>{t("title")}</h1>
        <p>{t("intro")}</p></div>
      {error && <div role="alert" className="error-banner">{t(error)} {!saving && <button onClick={() => { if (data && code && item) void save(); else setReload(n => n + 1); }}>{t("retry")}</button>}</div>}
      {loading ? <div className="empty-state"><Loader2 className="spin" />{t("loading")}</div> : !code ?
        <form onSubmit={login} className="login-card"><span className="eyebrow">{t("beforeBegin")}</span><h2>{t("enterCode")}</h2>
          <p>{t("resumeHelp")}</p><label htmlFor="evaluator">{t("evaluatorCode")}</label>
          <input id="evaluator" value={inputCode} onChange={e => setInputCode(e.target.value)} placeholder={t("codePlaceholder")} autoComplete="off" maxLength={64} required />
          <small>{t("codeHint")}</small><button className="primary-button" type="submit">{t("start")} <ArrowRight size={17} /></button></form> : !item ?
        <div className="empty-state">{t("questionsPreparing")}<button onClick={() => setReload(n => n + 1)}>{t("refresh")}</button></div> :
        <div className="evaluation-layout"><aside className="sidebar"><div className="progress-card">
          <span className="eyebrow">{t("progress")}</span><div className="progress-number"><strong>{count}</strong><span>{t("completedCount", { total })}</span></div>
          <progress value={count} max={total} aria-label={t("progress")} /><p>{t("progressHelp")}</p>
          <QuestionNavigator items={data!.items.map(q => ({ id: q.id, complete: isComplete(ratings[q.id]),
            unsaved: !!drafts[q.id] && (drafts[q.id].q1 !== (ratings[q.id]?.q1 ?? null) || drafts[q.id].q2 !== (ratings[q.id]?.q2 ?? null)),
          }))} currentIndex={index} disabled={saving} onNavigate={navigate} />
          <div className="reviewer"><span>{t("evaluator")}</span><strong>{code}</strong><button disabled={saving || hasUnsaved} onClick={() => { setCode(""); setInputCode(""); try { localStorage.removeItem(CODE_KEY); } catch { /* optional */ } }}>{t("switchCode")}</button></div>
        </div><div className="guide"><span>{t("ratingTips")}</span><p>{t("ratingTipsHelp")}</p><p>{t("reviseHelp")}</p></div></aside>
        <div className="question-column">
          {count === total && total > 0 && <div className="complete-banner"><CheckCircle2 size={21} /><div><strong>{t("completeTitle")}</strong><span>{t("completeHelp")}</span></div></div>}
          <section className="question-card"><div className="section-heading"><span className="eyebrow">{t("questionHeading", { number: String(index + 1).padStart(2, "0") })}</span><span className="muted">{index + 1} / {total}</span></div>
            <div className="query-block"><span className="language-tag">英文 / ENGLISH</span><p lang="en">{item.query_en}</p></div>
            <div className="query-block chinese"><span className="language-tag">繁體中文 / TRADITIONAL CHINESE</span><p lang="zh-Hant">{item.query_zh_tw}</p></div>
            <div className="rating-section"><span className="step-label">01 <ChevronRight size={14} /> {t("questionRealism")}</span>
              <fieldset disabled={saving}><legend>{t("q1")}</legend>
              <Choices name="q1" options={q1Options} value={current.q1} disabled={saving} onChange={q1 => update({ q1, q2: q1 === "unrealistic" ? null : current.q2 })} /></fieldset></div>
          </section>
          {showAnswer ? <section className="answer-card"><div className="section-heading"><span className="eyebrow">{t("answerHeading")}</span><span className="answer-label">{t("originalAnswer")}</span></div>
            <MediaPlaybackProvider value={item.playback_sources ?? {}}><div className="answer-body">{item.output_messages ? item.output_messages.map((message, i) => <div key={i}>
              <MarkdownText>{message.text}</MarkdownText>
              {message.media_urls.map((m, j) => <AttachmentTile key={j} attachment={toMediaAttachment(m)} />)}
            </div>) : <><MarkdownText>{item.answer}</MarkdownText>{item.media.map((m, i) => <AttachmentTile key={i} attachment={m} />)}</>}</div></MediaPlaybackProvider>
            <div className="rating-section"><span className="step-label">02 <ChevronRight size={14} /> {t("answerRelevance")}</span>
              <fieldset disabled={saving}><legend>{t("q2")}</legend>
              <Choices name="q2" options={q2Options} value={current.q2} disabled={saving} onChange={q2 => update({ q2 })} /></fieldset></div>
          </section> : <div className="answer-placeholder"><ClipboardCheck size={22} /><span>{current.q1 === "unrealistic" ? t("answerSkipped") : t("answerGated")}</span></div>}
          <footer className="action-bar"><button className="text-button" disabled={index === 0 || saving} onClick={() => navigate(index - 1)}><ArrowLeft size={16} />{t("previous")}</button>
            <div className="save-area"><span role="status" className={dirty ? "unsaved" : "saved"}>{t(saving ? "saving" : dirty ? "unsaved" : notice || (saved.updated_at ? "saved" : "notRated"))}</span>
              <button className="secondary-button" onClick={() => void save()} disabled={saving || !current.q1}><Save size={16} />{t("save")}</button>
              <button className="primary-button" onClick={() => void save(true)} disabled={saving || !isComplete(current)}>{saving ? <Loader2 className="spin" size={16} /> : null}{t(index === total - 1 ? "saveFinish" : "saveNext")}<ArrowRight size={16} /></button></div></footer>
        </div></div>}
      <div className="page-footnote">BadmintonGPT · {t("evaluation")} <span>{t("thanks")}</span></div>
    </main></div>;
}
