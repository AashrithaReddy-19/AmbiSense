import { useState } from "react";
import { api } from "../services/api";
export function EventReviewRow({
  event,
  onSaved,
}: {
  event: any;
  onSaved: () => void;
}) {
  const [note, setNote] = useState(event.reviewer_note || ""),
    [state, setState] = useState(event.review_state || "UNREVIEWED"),
    [included, setIncluded] = useState(Boolean(event.included_in_report)),
    [saving, setSaving] = useState(false),
    [feedback, setFeedback] = useState("");
  async function save() {
    setSaving(true);
    setFeedback("");
    try {
      await api.put(`/v1/events/${event.id}/review`, {
        review_state: state,
        reviewer_note: note || null,
        included_in_report: included && state !== "EXCLUDED",
      });
      setFeedback("Review saved.");
      onSaved();
    } catch (e: any) {
      setFeedback(e.response?.data?.detail || "Review could not be saved.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <article>
      <p>
        <time>{Number(event.timestamp).toFixed(1)}s</time> <b>{event.type}</b> ·{" "}
        {event.message}
      </p>
      <div className="live-controls">
        <select
          aria-label="Review state"
          value={state}
          onChange={(e) => {
            setState(e.target.value);
            if (e.target.value === "EXCLUDED") setIncluded(false);
          }}
        >
          {[
            "UNREVIEWED",
            "CONFIRMED",
            "INCORRECT",
            "UNCERTAIN",
            "EXCLUDED",
          ].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <input
          aria-label="Reviewer note"
          placeholder="Reviewer note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <label className="toggle">
          <span>Include in report</span>
          <input
            type="checkbox"
            checked={included}
            disabled={state === "EXCLUDED"}
            onChange={(e) => setIncluded(e.target.checked)}
          />
        </label>
        <button disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save review"}
        </button>
      </div>
      {feedback && <small>{feedback}</small>}
    </article>
  );
}
