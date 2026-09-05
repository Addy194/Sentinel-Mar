import axios from "axios";

export const api = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api` });

export const fmtTime = (iso) => (iso ? new Date(iso).toISOString().replace("T", " ").slice(0, 16) + "Z" : "—");
export const pct = (x) => `${Math.round((x || 0) * 100)}%`;

export const STATUS_LABEL = {
  indeterminate: "Indeterminate",
  insufficient_evidence: "Insufficient evidence",
  possible: "Possible",
  probable: "Probable",
  analyst_confirmed: "Analyst confirmed",
};

export const STATUS_STYLE = {
  possible: { color: "#FFB703", bg: "rgba(255,183,3,0.15)" },
  probable: { color: "#FF6B00", bg: "rgba(255,107,0,0.18)" },
  insufficient_evidence: { color: "#94A3B8", bg: "rgba(148,163,184,0.15)" },
  analyst_confirmed: { color: "#10B981", bg: "rgba(16,185,129,0.15)" },
  indeterminate: { color: "#C77DFF", bg: "rgba(157,78,221,0.15)" },
};

export const pollJob = async (jobId, onTick) => {
  for (let i = 0; i < 60; i++) {
    const { data } = await api.get(`/jobs/${jobId}`);
    onTick?.(data);
    if (data.status === "succeeded" || data.status === "failed") return data;
    await new Promise((r) => setTimeout(r, 800));
  }
  throw new Error("job polling timed out");
};
