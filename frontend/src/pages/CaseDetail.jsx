import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Download, Layers } from "lucide-react";
import { api, fmtTime, pct } from "@/lib/api";
import { StatusBadge, BandBadge } from "@/components/StatusBadge";
import { CaseMap } from "@/components/case/CaseMap";
import { CandidatesTable } from "@/components/case/CandidatesTable";
import { ReviewForm } from "@/components/case/ReviewForm";
import { EvidenceTimeline } from "@/components/case/EvidenceTimeline";
import { CorrelatePanel } from "@/components/case/CorrelatePanel";

const TABS = [["candidates", "Candidates"], ["review", "Analyst review"], ["evidence", "Evidence & audit"], ["log", "Processing log"]];

export default function CaseDetail() {
  const { id } = useParams();
  const [c, setC] = useState(null);
  const [cands, setCands] = useState(null);
  const [geo, setGeo] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [config, setConfig] = useState(null);
  const [tab, setTab] = useState("candidates");
  const [selected, setSelected] = useState(null);
  const [showTracks, setShowTracks] = useState(true);

  const load = useCallback(async () => {
    const [a, b, g, e, cfg] = await Promise.all([api.get(`/cases/${id}`), api.get(`/cases/${id}/candidates`), api.get(`/cases/${id}/geojson`), api.get(`/cases/${id}/evidence`), api.get("/config/defaults")]);
    setC(a.data); setCands(b.data); setGeo(g.data); setEvidence(e.data); setConfig(cfg.data);
  }, [id]);
  useEffect(() => { load().catch((e) => toast.error(e.message)); }, [load]);

  const exportGeo = () => {
    const blob = new Blob([JSON.stringify(geo, null, 2)], { type: "application/geo+json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${c.case_number}.geojson`; a.click();
  };

  if (!c) return <div className="p-6 font-mono text-xs text-slate-400" data-testid="case-loading">Loading case…</div>;
  const spill = c.spill_observation;

  return (
    <div className="flex h-full overflow-hidden" data-testid="case-detail">
      <div className="relative flex-1">
        <CaseMap geojson={geo} selected={selected} onSelect={setSelected} showTracks={showTracks} />
        <div className="absolute left-3 top-3 z-[1000] flex items-center gap-2">
          <Link to="/" data-testid="back-to-dashboard" className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider text-slate-200" style={{ background: "rgba(10,14,23,0.85)", border: "1px solid var(--border-highlight)", backdropFilter: "blur(12px)" }}><ArrowLeft size={12} /> Cases</Link>
          <button data-testid="map-toggle-ais-layer" onClick={() => setShowTracks(!showTracks)} className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider" style={{ background: "rgba(10,14,23,0.85)", border: "1px solid var(--border-highlight)", color: showTracks ? "#00F0FF" : "#94A3B8", backdropFilter: "blur(12px)" }}><Layers size={12} /> AIS tracks</button>
          <button data-testid="btn-export-geojson" onClick={exportGeo} className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider text-slate-200" style={{ background: "rgba(10,14,23,0.85)", border: "1px solid var(--border-highlight)", backdropFilter: "blur(12px)" }}><Download size={12} /> GeoJSON</button>
        </div>
        <div className="absolute bottom-3 left-3 z-[1000] rounded p-3 text-[11px]" style={{ background: "rgba(10,14,23,0.85)", border: "1px solid var(--border-default)", backdropFilter: "blur(12px)" }} data-testid="map-legend">
          <div className="flex items-center gap-2"><span className="h-2.5 w-4 border border-dashed" style={{ borderColor: "#FF2A6D", background: "rgba(255,42,109,0.35)" }} /> Spill polygon</div>
          <div className="flex items-center gap-2 mt-1"><span className="h-2.5 w-4 border border-dashed" style={{ borderColor: "#00F0FF" }} /> Search corridor</div>
          <div className="flex items-center gap-2 mt-1"><span className="h-0.5 w-4" style={{ background: "#FF2A6D" }} /> Rank 1 track · <span className="h-0.5 w-4" style={{ background: "#FFB703" }} /> Rank 2 …</div>
          <div className="flex items-center gap-2 mt-1"><span className="h-2 w-2 rounded-full border border-white" /> Drift back-projection</div>
        </div>
      </div>

      <aside className="flex w-[520px] shrink-0 flex-col border-l overflow-hidden" style={{ borderColor: "var(--border-default)", background: "var(--bg-secondary)" }}>
        <div className="border-b p-4" style={{ borderColor: "var(--border-default)" }}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="label-mono">{c.source} · det. conf {pct(c.detection_confidence)}</p>
              <h1 className="font-display text-2xl font-bold tracking-tight" data-testid="case-number">{c.case_number}</h1>
              <p className="font-mono text-xs text-slate-400">Acquired {fmtTime(c.acquisition_time)} · {spill?.estimated_area_km2} km² · v{c.latest_result_version}</p>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <StatusBadge status={c.attribution_status} testId="case-attribution-status" />
              <span className="font-mono text-[10px] text-slate-400">band <BandBadge band={c.confidence_band} /> · {c.review_state}</span>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {spill?.quality_flags?.map((f) => <span key={f} data-testid={`spill-flag-${f}`} className="rounded px-1.5 py-0.5 font-mono text-[10px] text-amber-300" style={{ background: "rgba(255,183,3,0.12)", border: "1px solid rgba(255,183,3,0.4)" }}>{f}</span>)}
            {cands?.degraded && <span data-testid="degraded-flag" className="rounded px-1.5 py-0.5 font-mono text-[10px] text-purple-300" style={{ background: "rgba(157,78,221,0.12)", border: "1px solid rgba(157,78,221,0.4)" }}>degraded: no drift inputs</span>}
            {cands?.ambiguous_multiple_vessels && <span data-testid="ambiguous-flag" className="rounded px-1.5 py-0.5 font-mono text-[10px] text-amber-300" style={{ background: "rgba(255,183,3,0.12)", border: "1px solid rgba(255,183,3,0.4)" }}>multiple-vessel ambiguity</span>}
            {c.confirmed_vessel_mmsi && <span data-testid="confirmed-vessel" className="rounded px-1.5 py-0.5 font-mono text-[10px] text-emerald-300" style={{ background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.4)" }}>confirmed MMSI {c.confirmed_vessel_mmsi}</span>}
          </div>
        </div>
        <CorrelatePanel caseId={id} defaults={config?.correlation_params} spill={spill} onDone={load} />
        <div className="flex border-b" style={{ borderColor: "var(--border-default)" }}>
          {TABS.map(([k, l]) => (
            <button key={k} data-testid={`tab-${k}`} onClick={() => setTab(k)} className={`px-4 py-2 font-mono text-[11px] uppercase tracking-wider transition-colors ${tab === k ? "text-cyan-300 border-b-2 border-cyan-300" : "text-slate-400 hover:text-slate-100"}`}>{l}</button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto">
          {tab === "candidates" && (
            <>
              <p className="px-4 pt-3 text-[11px] text-slate-500" data-testid="candidates-disclaimer">{cands?.disclaimer || "Ranked candidates are decision-support output, not a legal determination."}</p>
              <CandidatesTable candidates={cands?.candidates} selected={selected} onSelect={setSelected} />
            </>
          )}
          {tab === "review" && <ReviewForm caseId={id} candidates={cands?.candidates} reasonCodes={config?.reason_codes} resultVersion={cands?.version} onSaved={load} />}
          {tab === "evidence" && <EvidenceTimeline evidence={evidence} />}
          {tab === "log" && (
            <div className="p-4 font-mono text-[11px] leading-relaxed" data-testid="processing-log">
              {evidence?.calculations?.processing_log?.map((l, i) => (
                <div key={i} className={l.level === "warn" ? "text-amber-300" : "text-slate-300"}><span className="text-slate-600">{l.t.slice(11, 19)}</span> {l.msg}</div>
              )) || <p className="text-slate-500">No processing log yet.</p>}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
