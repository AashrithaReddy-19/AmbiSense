import { ChevronLeft, ChevronRight } from "lucide-react";

export function Pagination({ page, pages, total, onPage, noun = "results" }: { page: number; pages: number; total: number; onPage: (page: number) => void; noun?: string }) {
  if (total === 0) return null;
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted" aria-live="polite">Page {page} of {pages} · {total} {noun}</span>
      <div className="actions">
        <button className="button secondary" style={{ marginTop: 0 }} disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /> Previous</button>
        <button className="button secondary" style={{ marginTop: 0 }} disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">Next <ChevronRight size={14} /></button>
      </div>
    </nav>
  );
}
