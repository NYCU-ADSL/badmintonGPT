import { useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

const PAGE_SIZE = 20;
type Entry = { id: string; complete: boolean; unsaved: boolean };

export function QuestionNavigator({ items, currentIndex, disabled, onNavigate }: {
  items: Entry[]; currentIndex: number; disabled: boolean; onNavigate: (index: number) => void;
}) {
  const { t } = useTranslation("evaluation");
  const [page, setPage] = useState(() => Math.floor(currentIndex / PAGE_SIZE));
  const [jump, setJump] = useState("");
  const [invalidJump, setInvalidJump] = useState(false);
  const total = items.length;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  const activePage = Math.min(page, Math.max(0, pageCount - 1));
  const start = activePage * PAGE_SIZE;
  const currentPage = Math.floor(currentIndex / PAGE_SIZE);
  // Keep the active question visible after resume, direct jumps and Save & next.
  useEffect(() => { setPage(Math.floor(currentIndex / PAGE_SIZE)); }, [currentIndex, total]);

  function goTo(index: number) {
    if (disabled) return;
    setPage(Math.floor(index / PAGE_SIZE));
    setInvalidJump(false);
    onNavigate(index);
  }
  function submitJump(event: FormEvent) {
    event.preventDefault();
    const number = Number(jump);
    if (!Number.isInteger(number) || number < 1 || number > total) {
      setInvalidJump(true);
      return;
    }
    goTo(number - 1);
    setJump("");
  }
  // Start after the current question and wrap around. Completion is saved progress.
  let nextIncomplete = -1;
  for (let offset = 1; offset <= total; offset++) {
    const candidate = (currentIndex + offset) % total;
    if (!items[candidate].complete) { nextIncomplete = candidate; break; }
  }

  return <nav className="question-navigator" aria-label={t("questionNavigation")}>
    <div className="navigation-current">{t("currentQuestion", { number: currentIndex + 1, total })}</div>
    {pageCount > 1 && <div className="question-pagination">
      <button type="button" disabled={disabled || activePage === 0} onClick={() => setPage(activePage - 1)}
        aria-label={t("previousQuestionPage")}><ArrowLeft size={15} /></button>
      <span aria-live="polite">{t("questionRange", { start: start + 1, end: Math.min(start + PAGE_SIZE, total), total })}</span>
      <button type="button" disabled={disabled || activePage >= pageCount - 1} onClick={() => setPage(activePage + 1)}
        aria-label={t("nextQuestionPage")}><ArrowRight size={15} /></button>
    </div>}
    <div className="question-grid">{items.slice(start, start + PAGE_SIZE).map((item, offset) => {
      const index = start + offset;
      const label = t(item.unsaved ? "questionNavUnsaved" : item.complete ? "questionNavCompleted" : "questionNav", { number: index + 1 });
      return <button type="button" key={item.id} disabled={disabled} onClick={() => goTo(index)}
        className={`${index === currentIndex ? "active" : ""} ${item.complete ? "done" : ""}`}
        aria-label={label} title={label} aria-current={index === currentIndex ? "step" : undefined}>
        {String(index + 1).padStart(2, "0")}
        {item.unsaved ? <span className="draft-dot" aria-hidden="true" /> : item.complete ? <Check size={10} className="question-complete" aria-hidden="true" /> : null}
      </button>;
    })}</div>
    <div className="navigation-legend"><span><Check size={12} />{t("completed")}</span><span><span className="draft-dot" />{t("unsaved")}</span></div>
    {activePage !== currentPage && <button type="button" className="return-current" disabled={disabled}
      onClick={() => setPage(currentPage)}>{t("returnToCurrent")}</button>}
    <form className="question-jump" onSubmit={submitJump} noValidate>
      <label htmlFor="question-number">{t("jumpToQuestion")}</label>
      <div><input id="question-number" type="number" inputMode="numeric" min={1} max={total} step={1}
        placeholder={`1–${total}`} value={jump} disabled={disabled} aria-invalid={invalidJump}
        aria-describedby={invalidJump ? "question-jump-error" : undefined}
        onChange={event => { setJump(event.target.value); setInvalidJump(false); }} />
        <button type="submit" disabled={disabled || !jump.trim()}>{t("goToQuestion")}</button></div>
      {invalidJump && <p id="question-jump-error" role="alert">{t("invalidQuestionNumber", { total })}</p>}
    </form>
    <button type="button" className="next-incomplete" disabled={disabled || nextIncomplete < 0}
      onClick={() => goTo(nextIncomplete)}>{t("nextIncomplete")}<ArrowRight size={14} /></button>
  </nav>;
}
