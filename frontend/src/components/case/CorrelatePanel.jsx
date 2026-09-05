import { useState } from "react";
import { Play, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { api, pollJob } from "@/lib/api";

const num = "w-full rounded border bg-slate-900/60 px-2 py-1 font-mono text-xs text-slate-100 outline-none focus:border-cyan-400/60";

export const CorrelatePanel = ({ caseId, defaults, spill, onDone }) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState(null);
  const [p, setP] = useState({ corridor_km: defaults?.corridor_km ?? 25, window_hours_before: defaults?.window_hours_before ?? 24, window_hours_after: defaults?.window_hours_after ?? 3, min_positions: defaults?.min_positions ?? 2, spill_age_hours: spill?.estimated_age_hours ?? "" });
  const [wind, setWind] = useState({ on: false, speed_ms: spill?.wind?.speed_ms ?? 8, direction_deg: spill?.wind?.direction_deg ?? 240 });
  const [cur, setCur] = useState({ on: false, speed_ms: spill?.current?.speed_ms ?? 0.3, direction_deg: spill?.current?.direction_deg ?? 45 });

  const run = async () => {
    setBusy(true); setLog("queued…");
    try {
      const params = { corridor_km: +p.corridor_km, window_hours_before: +p.window_hours_before, window_hours_after: +p.window_hours_after, min_positions: +p.min_positions,
        spill_age_hours: p.spill_age_hours === "" ? null : +p.spill_age_hours,
        wind: wind.on ? { speed_ms: +wind.speed_ms, direction_deg: +wind.direction_deg } : null,
        current: cur.on ? { speed_ms: +cur.speed_ms, direction_deg: +cur.direction_deg } : null };
      const { data: job } = await api.post(`/cases/${caseId}/correlate`, { params, sync: false, actor: "duty-analyst" });
      toast.info(`Correlation job ${job.id.slice(0, 8)} queued`);
      const done = await pollJob(job.id, (j) => setLog(`${j.status} · attempt ${j.attempts}`));
      if (done.status === "succeeded") { toast.success(`Result v${done.result.version}: ${done.result.overall_status}`); onDone?.(); }
      else toast.error(`Job failed: ${done.error}`);
      setLog(null);
    } catch (e) { toast.error(e.response?.data?.detail?.[0]?.msg || e.message); setLog(null); }
    finally { setBusy(false); }
  };

  return (
    <div className="border-b" style={{ borderColor: "var(--border-default)" }} data-testid="correlate-panel">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <button data-testid="btn-correlate-run" disabled={busy} onClick={run} className="inline-flex items-center gap-1.5 rounded bg-cyan-400 px-3 py-1.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-slate-950 hover:bg-cyan-300 disabled:opacity-50">
          <Play size={12} /> {busy ? "Running…" : "Run correlation"}
        </button>
        <button data-testid="btn-correlate-params-toggle" onClick={() => setOpen(!open)} className="inline-flex items-center gap-1.5 rounded border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-slate-300 hover:text-white" style={{ borderColor: "var(--border-highlight)" }}>
          <Settings2 size={12} /> Parameters
        </button>
        {log && <span className="font-mono text-[11px] text-cyan-300" data-testid="correlate-job-status">{log}</span>}
      </div>
      {open && (
        <div className="grid grid-cols-2 gap-2 px-4 pb-3 sm:grid-cols-4 fade-up" data-testid="correlate-params">
          {[["corridor_km", "Corridor km"], ["window_hours_before", "Window −h"], ["window_hours_after", "Window +h"], ["min_positions", "Min fixes"], ["spill_age_hours", "Spill age h"]].map(([k, l]) => (
            <label key={k} className="block"><span className="label-mono block mb-0.5">{l}</span>
              <input data-testid={`param-${k}`} className={num} style={{ borderColor: "var(--border-highlight)" }} value={p[k]} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></label>
          ))}
          <EnvRow label="Wind (m/s, FROM°)" v={wind} set={setWind} tid="wind" />
          <EnvRow label="Current (m/s, TOWARD°)" v={cur} set={setCur} tid="current" />
          <p className="col-span-full text-[11px] text-slate-500">Leave wind/current off to inherit the observation's environment; if none exists, attribution is marked degraded.</p>
        </div>
      )}
    </div>
  );
};

const EnvRow = ({ label, v, set, tid }) => (
  <div className="col-span-2 flex items-end gap-2">
    <label className="flex items-center gap-1.5 pb-1.5 text-[11px] text-slate-300"><input type="checkbox" data-testid={`param-${tid}-override`} checked={v.on} onChange={(e) => set({ ...v, on: e.target.checked })} /> {label}</label>
    <input data-testid={`param-${tid}-speed`} className={`${num} w-16`} style={{ borderColor: "var(--border-highlight)" }} disabled={!v.on} value={v.speed_ms} onChange={(e) => set({ ...v, speed_ms: e.target.value })} />
    <input data-testid={`param-${tid}-dir`} className={`${num} w-16`} style={{ borderColor: "var(--border-highlight)" }} disabled={!v.on} value={v.direction_deg} onChange={(e) => set({ ...v, direction_deg: e.target.value })} />
  </div>
);
