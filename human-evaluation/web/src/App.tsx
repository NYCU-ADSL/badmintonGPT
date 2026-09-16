import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight, ClipboardCheck, Loader2, Save } from "lucide-react";
import { MarkdownText } from "@/components/MarkdownText";
import { AttachmentTile } from "@/components/AttachmentTile";
import type { UIMediaAttachment } from "@/lib/types";

type Rating = { q1: string | null; q2: string | null; updated_at?: string };
type OutputMessage = { text: string; media_urls: {url: string; name?: string}[] };
type Item = { id: string; query_en: string; query_zh_tw: string; answer: string; media: UIMediaAttachment[]; output_messages?: OutputMessage[] };
type Dataset = { id: string; model: string; target_count: number; items: Item[] };
type RatingResult = { ratings: (Rating & { item_id: string })[] };
const EMPTY: Rating = { q1: null, q2: null };
const CODE_KEY = "badmintongpt-evaluator-code";
export const isComplete = (r?: Rating) => !!r && (r.q1 === "unrealistic" ||
  (["realistic", "somewhat_realistic"].includes(r.q1 ?? "") && !!r.q2));

const q1Options = [
  ["realistic", "合理", "Realistic", "有自然、可信的提問動機，真實使用者可能會這樣問。"],
  ["somewhat_realistic", "有些牽強", "Somewhat realistic", "可以想像有人會問，但情境或需求刻意、不太自然。"],
  ["unrealistic", "不合理", "Unrealistic", "缺乏可信的使用情境，像是為了生成問題而硬湊出來的。"],
];
const q2Options = [
  ["fully_addresses", "完全符合", "Fully addresses", "回答直接切題，涵蓋使用者的主要需求與明確限制。"],
  ["partially_addresses", "部分符合", "Partially addresses", "回答與問題相關，但遺漏部分需求，或部分內容偏離問題。"],
  ["does_not_address", "不符合", "Does not address", "誤解使用者意圖、答非所問，或沒有回應核心問題。"],
];

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "無法儲存或讀取資料，請稍後重試。");
  }
  return response.json();
}

function storedCode() { try { return localStorage.getItem(CODE_KEY) ?? ""; } catch { return ""; } }

function Choices({ name, options, value, onChange, disabled }: {
  name: string; options: string[][]; value: string | null; onChange: (value: string) => void; disabled: boolean;
}) {
  return <div className="choices">{options.map(([id, label, english, description]) =>
    <label className={`choice ${value === id ? "selected" : ""}`} key={id}>
      <input type="radio" name={name} value={id} checked={value === id} onChange={() => onChange(id)} disabled={disabled} />
      <span><strong>{label} <small>{english}</small></strong><span className="criterion">{description}</span></span>
      {value === id && <Check size={17} className="choice-check" />}
    </label>)}</div>;
}

export default function App() {
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
    }).catch(e => { if (!cancelled) setError(e.message); })
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
    if (!/^[A-Za-z0-9_-]{3,64}$/.test(next)) { setError("請輸入 3–64 個英文字母、數字、底線或連字號。"); return; }
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
      setNotice("已儲存至伺服器");
      if (next && index < total - 1) navigate(index + 1);
    } catch (e) { setError((e as Error).message); }
    finally { saveLock.current = false; setSaving(false); }
  }

  return <div className="evaluation-app">
    <header className="topbar"><div className="brandmark"><span className="logo"><ClipboardCheck size={22} /></span>
      <div><strong>BadmintonGPT</strong><span>HUMAN EVALUATION</span></div></div>
      <span className="pilot-badge">PILOT STUDY · {data?.target_count ?? 10} QUESTIONS</span></header>
    <main className="page-shell">
      <div className="intro"><span className="eyebrow">讓每一份回答，更貼近真實需求</span><h1>你的判斷，讓評測更有意義。</h1>
        <p>先看問題是否自然，再判斷回答是否切題。每一題都依照你的直覺與判斷評分。</p></div>
      {error && <div role="alert" className="error-banner">{error} {!saving && <button onClick={() => { if (data && code && item) void save(); else setReload(n => n + 1); }}>重試</button>}</div>}
      {loading ? <div className="empty-state"><Loader2 className="spin" />正在載入評測…</div> : !code ?
        <form onSubmit={login} className="login-card"><span className="eyebrow">開始之前</span><h2>輸入你的評測代碼</h2>
          <p>下次使用相同代碼，即可接續伺服器上保存的進度。</p><label htmlFor="evaluator">評測代碼</label>
          <input id="evaluator" value={inputCode} onChange={e => setInputCode(e.target.value)} placeholder="例如 reviewer-01" autoComplete="off" maxLength={64} required />
          <small>3–64 個英文字母、數字、底線或連字號；代碼區分大小寫。</small><button className="primary-button" type="submit">開始評測 <ArrowRight size={17} /></button></form> : !item ?
        <div className="empty-state">題目正在準備中。<button onClick={() => setReload(n => n + 1)}>重新整理</button></div> :
        <div className="evaluation-layout"><aside className="sidebar"><div className="progress-card">
          <span className="eyebrow">YOUR PROGRESS</span><div className="progress-number"><strong>{count}</strong><span>/ {total} 題完成</span></div>
          <progress value={count} max={total} aria-label="評測進度" /><p>進度以已儲存的完整評分計算。</p>
          <div className="question-grid">{data!.items.map((q, i) => <button key={q.id} disabled={saving} onClick={() => navigate(i)}
            className={`${i === index ? "active" : ""} ${isComplete(ratings[q.id]) ? "done" : ""}`}
            aria-label={`第 ${i + 1} 題${isComplete(ratings[q.id]) ? "，已完成" : ""}`} aria-current={i === index ? "step" : undefined}>
            {isComplete(ratings[q.id]) ? <Check size={17} /> : String(i + 1).padStart(2, "0")}</button>)}</div>
          <div className="reviewer"><span>評測者</span><strong>{code}</strong><button disabled={saving || hasUnsaved} onClick={() => { setCode(""); setInputCode(""); try { localStorage.removeItem(CODE_KEY); } catch { /* optional */ } }}>切換代碼</button></div>
        </div><div className="guide"><span>評分小提醒</span><p>「合理」看提問動機；<br/>「符合」看回答是否涵蓋需求。</p><p>你可以隨時回到前面的題目，調整並重新儲存評分。</p></div></aside>
        <div className="question-column">
          {count === total && total > 0 && <div className="complete-banner"><CheckCircle2 size={21} /><div><strong>全部評測已完成，謝謝你！</strong><span>評分已儲存，你仍可返回修改。</span></div></div>}
          <section className="question-card"><div className="section-heading"><span className="eyebrow">QUESTION {String(index + 1).padStart(2, "0")}</span><span className="muted">{index + 1} / {total}</span></div>
            <div className="query-block"><span className="language-tag">ENGLISH</span><p lang="en">{item.query_en}</p></div>
            <div className="query-block chinese"><span className="language-tag">繁體中文</span><p lang="zh-Hant">{item.query_zh_tw}</p></div>
            <div className="rating-section"><span className="step-label">01 <ChevronRight size={14} /> 問題合理性</span>
              <fieldset disabled={saving}><legend>Is this a realistic question that a user might ask BadmintonGPT?</legend>
              <p className="question-translation">這是真實使用者可能會提出的問題嗎？</p>
              <Choices name="q1" options={q1Options} value={current.q1} disabled={saving} onChange={q1 => update({ q1, q2: q1 === "unrealistic" ? null : current.q2 })} /></fieldset></div>
          </section>
          {showAnswer ? <section className="answer-card"><div className="section-heading"><span className="eyebrow">BADMINTONGPT’S ANSWER</span><span className="answer-label">原始回答</span></div>
            <div className="answer-body">{item.output_messages ? item.output_messages.map((message, i) => <div key={i}>
              <MarkdownText>{message.text}</MarkdownText>
              {message.media_urls.map((m, j) => <AttachmentTile key={j} attachment={{...m, kind: /\.(mp4|webm|mov)$/i.test(m.name ?? "") ? "video" : /\.(png|jpe?g|gif|webp)$/i.test(m.name ?? "") ? "image" : "file"}} />)}
            </div>) : <><MarkdownText>{item.answer}</MarkdownText>{item.media.map((m, i) => <AttachmentTile key={i} attachment={m} />)}</>}</div>
            <div className="rating-section"><span className="step-label">02 <ChevronRight size={14} /> 回答符合程度</span>
              <fieldset disabled={saving}><legend>Does BadmintonGPT’s answer address the user’s question and intent?</legend>
              <p className="question-translation">回答是否回應使用者的問題與意圖？</p>
              <Choices name="q2" options={q2Options} value={current.q2} disabled={saving} onChange={q2 => update({ q2 })} /></fieldset></div>
          </section> : <div className="answer-placeholder"><ClipboardCheck size={22} /><span>{current.q1 === "unrealistic" ? "這題不需評回答，儲存後即可完成。" : "完成問題合理性評分後，再進行回答評分。"}</span></div>}
          <footer className="action-bar"><button className="text-button" disabled={index === 0 || saving} onClick={() => navigate(index - 1)}><ArrowLeft size={16} />上一題</button>
            <div className="save-area"><span role="status" className={dirty ? "unsaved" : "saved"}>{saving ? "儲存中…" : dirty ? "尚未儲存" : notice || (saved.updated_at ? "已儲存" : "尚未評分")}</span>
              <button className="secondary-button" onClick={() => void save()} disabled={saving || !current.q1}><Save size={16} />儲存</button>
              <button className="primary-button" onClick={() => void save(true)} disabled={saving || !isComplete(current)}>{saving ? <Loader2 className="spin" size={16} /> : null}{index === total - 1 ? "儲存並完成" : "儲存並下一題"}<ArrowRight size={16} /></button></div></footer>
        </div></div>}
      <div className="page-footnote">BadmintonGPT · Human Evaluation <span>謝謝你協助我們理解真實使用體驗。</span></div>
    </main></div>;
}
