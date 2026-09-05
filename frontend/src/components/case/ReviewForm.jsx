import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const inputCls = "w-full rounded border bg-slate-900/60 px-2.5 py-1.5 text-sm text-slate-100 outline-none focus:border-cyan-400/60";

export const ReviewForm = ({ caseId, candidates, reasonCodes, resultVersion, onSaved }) => {
  const [decision, setDecision] = useState("confirm");
  const [mmsi, setMmsi] = useState(candidates?.[0]?.mmsi || "");
  const [codes, setCodes] = useState([]);
  const [notes, setNotes] = useState("");
  const [analyst, setAnalyst] = useState("duty-analyst");
  const [busy, setBusy] = useState(false);

  const toggle = (c) => setCodes((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]));

  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/cases/${caseId}/review`, { decision, vessel_mmsi: decision === "confirm" ? mmsi : mmsi || null, reason_codes: codes, notes, analyst, result_version: resultVersion || null });
      toast.success(`Review recorded: ${decision.replace("_", " ")}`);
      setNotes(""); setCodes([]);
      onSaved?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 p-4" data-testid="review-form">
      <p className="text-xs text-slate-400">Analyst decisions are immutable and appended to the audit trail. Prior automated results are preserved.</p>
      <div className="grid grid-cols-3 gap-2">
        {[["confirm", "Confirm", "#10B981", "btn-confirm-analyst-review"], ["reject", "Reject", "#FF2A6D", "btn-reject-analyst-review"], ["needs_more_data", "Needs data", "#FFB703", "btn-needs-data-analyst-review"]].map(([v, l, col, tid]) => (
          <button key={v} data-testid={tid} onClick={() => setDecision(v)}
            className="rounded border px-2 py-2 font-mono text-[11px] uppercase tracking-wider transition-colors"
            style={{ borderColor: decision === v ? col : "var(--border-highlight)", color: decision === v ? col : "#94A3B8", background: decision === v ? `${col}18` : "transparent" }}>
            {l}
          </button>
        ))}
      </div>
      <div>
        <label className="label-mono block mb-1">Vessel {decision === "confirm" && <span className="text-crimson-400" style={{ color: "#FF2A6D" }}>*</span>}</label>
        <select data-testid="review-vessel-select" value={mmsi} onChange={(e) => setMmsi(e.target.value)} className={inputCls} style={{ borderColor: "var(--border-highlight)" }}>
          <option value="">— none —</option>
          {candidates?.map((c) => <option key={c.mmsi} value={c.mmsi}>#{c.rank} {c.vessel_name || c.mmsi} ({c.mmsi})</option>)}
        </select>
      </div>
      <div>
        <label className="label-mono block mb-1">Reason codes</label>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(reasonCodes || {}).map(([code, desc]) => (
            <button key={code} title={desc} data-testid={`reason-code-${code}`} onClick={() => toggle(code)}
              className={`rounded px-2 py-1 font-mono text-[10px] transition-colors ${codes.includes(code) ? "bg-cyan-400/15 text-cyan-300 border border-cyan-400/50" : "border border-slate-700 text-slate-400 hover:text-slate-100"}`}>
              {code.split("_")[0]}
            </button>
          ))}
        </div>
        {codes.length > 0 && <p className="mt-1.5 text-[11px] text-slate-400">{codes.map((c) => reasonCodes[c]).join(" · ")}</p>}
      </div>
      <div>
        <label className="label-mono block mb-1">Notes</label>
        <textarea data-testid="review-notes-input" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={inputCls} style={{ borderColor: "var(--border-highlight)" }} placeholder="Corroborating intel, inspection results, uncertainty remarks…" />
      </div>
      <div className="flex items-center gap-2">
        <input data-testid="review-analyst-input" value={analyst} onChange={(e) => setAnalyst(e.target.value)} className={`${inputCls} flex-1`} style={{ borderColor: "var(--border-highlight)" }} placeholder="analyst id" />
        <button data-testid="review-submit-button" disabled={busy} onClick={submit} className="rounded bg-cyan-400 px-4 py-1.5 font-mono text-xs font-semibold uppercase tracking-wider text-slate-950 hover:bg-cyan-300 disabled:opacity-50">
          {busy ? "Saving…" : "Record decision"}
        </button>
      </div>
    </div>
  );
};
