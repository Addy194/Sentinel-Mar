import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Polyline, Popup, Tooltip, ImageOverlay, useMap } from "react-leaflet";
import L from "leaflet";
import { fmtTime } from "@/lib/api";
import { GibsLayer } from "@/components/map/GibsLayer";
import { TILE_PERF, OSM_URL } from "@/components/map/tiles";

const FitTo = ({ bounds }) => {
  const map = useMap();
  useEffect(() => { if (bounds) map.flyToBounds(bounds, { padding: [80, 80], maxZoom: 13, duration: 0.8 }); }, [bounds, map]);
  return null;
};

const RANK_COLORS = ["#FF2A6D", "#FFB703", "#00F0FF", "#9D4EDD", "#38BDF8", "#10B981"];
const rankColorFor = (rank) => RANK_COLORS[Math.min((rank || 1) - 1, RANK_COLORS.length - 1)];

const FitBounds = ({ geojson }) => {
  const map = useMap();
  useEffect(() => {
    if (!geojson?.features?.length) return;
    const b = L.geoJSON(geojson).getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [24, 24] });
    setTimeout(() => map.invalidateSize(), 50);
  }, [geojson, map]);
  return null;
};

// Position of a track at time t (ms): interpolated between fixes; null if before first fix.
export const trackPositionAt = (feature, t) => {
  const ts = feature.properties.timestamps.map((x) => new Date(x).getTime());
  const coords = feature.geometry.coordinates;
  if (t < ts[0]) return null;
  if (t >= ts[ts.length - 1]) return { lat: coords[ts.length - 1][1], lon: coords[ts.length - 1][0], idx: ts.length - 1, stale: t - ts[ts.length - 1] > 2 * 3600e3 };
  let i = 0;
  while (i < ts.length - 1 && ts[i + 1] <= t) i++;
  const f = (t - ts[i]) / Math.max(ts[i + 1] - ts[i], 1);
  return { lat: coords[i][1] + (coords[i + 1][1] - coords[i][1]) * f, lon: coords[i][0] + (coords[i + 1][0] - coords[i][0]) * f, idx: i, gap: ts[i + 1] - ts[i] > 2 * 3600e3 };
};

export const CaseMap = ({ geojson, selected, onSelect, showTracks = true, showCorridor = true, timeCursor = null, acquisitionTime = null, zones = null, sideColors = null, gibs = null, overlay = null, fitTo = null, highlight = null }) => {
  const colorFor = (rank, side) => (sideColors && side ? sideColors[side] : RANK_COLORS[Math.min((rank || 1) - 1, RANK_COLORS.length - 1)]);
  const layers = useMemo(() => {
    const f = geojson?.features || [];
    return {
      spill: f.filter((x) => x.properties.layer === "spill"),
      corridor: f.filter((x) => x.properties.layer === "corridor"),
      tracks: f.filter((x) => x.properties.layer === "track"),
      fixes: f.filter((x) => x.properties.layer === "closest_fix"),
      bp: f.filter((x) => x.properties.layer === "backprojected_centroid"),
      driftEnv: f.filter((x) => x.properties.layer === "drift_envelope"),
      driftLikely: f.filter((x) => x.properties.layer === "drift_likely"),
      driftPath: f.filter((x) => x.properties.layer === "drift_path"),
    };
  }, [geojson]);
  const acqMs = acquisitionTime ? new Date(acquisitionTime).getTime() : null;
  const spillVisible = timeCursor == null || acqMs == null || timeCursor >= acqMs;

  return (
    <div className="h-full w-full" data-testid="case-map">
    <MapContainer center={[53.5, 3.8]} zoom={9} className="h-full w-full" zoomControl>
      <TileLayer url={OSM_URL} attribution='&copy; OpenStreetMap contributors' className="dark-tiles" {...TILE_PERF} />
      {gibs && acquisitionTime && <GibsLayer layer={gibs.layer} date={acquisitionTime.slice(0, 10)} template={gibs.template} />}
      {overlay?.url && overlay.bounds && <ImageOverlay url={overlay.url} bounds={overlay.bounds} opacity={overlay.opacity ?? 0.8} zIndex={5} />}
      <FitTo bounds={fitTo} />
      {highlight && (
        <CircleMarker center={[highlight.lat, highlight.lon]} radius={14} pathOptions={{ color: highlight.confirmed ? "#FF2A6D" : "#FFB703", weight: 3, fillOpacity: 0.15, dashArray: highlight.confirmed ? null : "4,4" }}>
          <Tooltip permanent direction="top" offset={[0, -14]} className="focus-tip"><span data-testid="focus-vessel-label">{highlight.confirmed ? "RESPONSIBLE (analyst confirmed)" : "TOP CANDIDATE — not confirmed"} · {highlight.name}</span></Tooltip>
        </CircleMarker>
      )}
      <FitBounds geojson={geojson} />
      {zones?.features?.length > 0 && (
        <GeoJSON key={`zones-${zones.features.length}`} data={zones}
          style={(ft) => ({ color: ft.properties.zone_type === "port_state" ? "#FFB703" : "#38BDF8", weight: 1, opacity: 0.55, fillOpacity: 0.04, dashArray: "2,6" })}
          onEachFeature={(ft, layer) => layer.bindTooltip(`${ft.properties.code} · ${ft.properties.authority}`, { sticky: true })} />
      )}
      {showCorridor && layers.corridor.map((f, i) => (
        <GeoJSON key={`c${i}`} data={f} style={{ color: "#00F0FF", weight: 1, dashArray: "6,6", fillColor: "#00F0FF", fillOpacity: 0.05 }} />
      ))}
      {showCorridor && layers.driftEnv.map((f, i) => (
        <GeoJSON key={`de${i}`} data={f} style={{ color: "#C77DFF", weight: 1.5, dashArray: "2,4", fillColor: "#9D4EDD", fillOpacity: 0.12 }}>
          <Tooltip sticky><span data-testid="drift-envelope-tip">Origin envelope · 2σ · {f.properties.hours}h backward Lagrangian model</span></Tooltip>
        </GeoJSON>
      ))}
      {showCorridor && layers.driftLikely.map((f, i) => (
        <GeoJSON key={`dl${i}`} data={f} style={{ color: "#C77DFF", weight: 2, fillColor: "#C77DFF", fillOpacity: 0.22 }}>
          <Tooltip sticky>Most-likely origin window: {f.properties.window_hours[0]}–{f.properties.window_hours[1]} h before acquisition</Tooltip>
        </GeoJSON>
      ))}
      {showCorridor && layers.driftPath.map((f, i) => (
        <Polyline key={`dp${i}`} positions={f.geometry.coordinates.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: "#C77DFF", weight: 2, dashArray: "1,6", opacity: 0.9 }} />
      ))}
      {layers.spill.map((f, i) => (
        <GeoJSON key={`s${i}-${f.properties.id}-${spillVisible}`} data={f} style={{ color: sideColors?.[f.properties.side] || "#FF2A6D", weight: 2, dashArray: "4,4", fillColor: sideColors?.[f.properties.side] || "#FF2A6D", fillOpacity: spillVisible ? 0.35 : 0.06, opacity: spillVisible ? 1 : 0.35 }}>
          <Popup><b>Spill observation</b><br />Acquired {fmtTime(f.properties.acquisition_time)}<br />Confidence {Math.round(f.properties.detection_confidence * 100)}% · {f.properties.estimated_area_km2} km²<br />{f.properties.quality_flags?.join(", ") || "no quality flags"}</Popup>
        </GeoJSON>
      ))}
      {showTracks && layers.tracks.map((f) => {
        const p = f.properties;
        const dim = selected && selected !== p.mmsi;
        let coords = f.geometry.coordinates;
        let head = null;
        if (timeCursor != null) {
          head = trackPositionAt(f, timeCursor);
          if (!head) return null;
          coords = [...coords.slice(0, head.idx + 1), [head.lon, head.lat]];
        }
        return (
          <Polyline key={`t${p.side || ""}${p.mmsi}-${p.segment ?? 0}`} positions={coords.map(([lon, lat]) => [lat, lon])}
            pathOptions={{ color: colorFor(p.rank, p.side), weight: dim ? 1.5 : p.interpolated ? 2 : 3, opacity: dim ? 0.3 : p.interpolated ? 0.7 : 0.85, dashArray: p.interpolated ? "6,8" : null }}
            eventHandlers={{ click: () => onSelect?.(p.mmsi) }}>
            {p.interpolated && <Tooltip sticky><span data-testid="interpolated-tip">Interpolated (dead reckoning across AIS gap) — not a transmitted position</span></Tooltip>}
          </Polyline>
        );
      })}
      {showTracks && timeCursor != null && layers.tracks.map((f) => {
        const p = f.properties;
        const head = trackPositionAt(f, timeCursor);
        if (!head) return null;
        const dim = selected && selected !== p.mmsi;
        return (
          <CircleMarker key={`h${p.side || ""}${p.mmsi}`} center={[head.lat, head.lon]} radius={p.rank === 1 ? 9 : 7}
            pathOptions={{ color: "#F8FAFC", fillColor: colorFor(p.rank, p.side), fillOpacity: dim ? 0.3 : 1, weight: 2, dashArray: head.gap || head.stale ? "3,3" : null, opacity: dim ? 0.3 : 1 }}
            eventHandlers={{ click: () => onSelect?.(p.mmsi) }}>
            <Popup><b>#{p.rank} {p.vessel_name || p.mmsi}</b><br />{fmtTime(new Date(timeCursor).toISOString())}{head.gap || head.stale ? <><br /><i>inside AIS gap — position interpolated</i></> : null}</Popup>
          </CircleMarker>
        );
      })}
      {timeCursor == null && layers.fixes.map((f) => {
        const p = f.properties;
        const [lon, lat] = f.geometry.coordinates;
        return (
          <CircleMarker key={`f${p.side || ""}${p.mmsi}`} center={[lat, lon]} radius={p.rank === 1 ? 8 : 6}
            pathOptions={{ color: colorFor(p.rank, p.side), fillColor: colorFor(p.rank, p.side), fillOpacity: selected === p.mmsi ? 1 : 0.7, weight: 2 }}
            eventHandlers={{ click: () => onSelect?.(p.mmsi) }}>
            <Popup>
              <b>#{p.rank} {p.vessel_name || p.mmsi}</b><br />MMSI {p.mmsi} · score {p.score?.toFixed(3)} · {p.status}<br />
              Closest approach {fmtTime(p.timestamp)}<br />{p.distance_km} km from slick · {p.time_gap_hours}h {p.time_gap_hours >= 0 ? "before" : "after"} acquisition<br />
              SOG {p.sog_kn ?? "—"} kn · COG {p.cog_deg ?? "—"}°
            </Popup>
          </CircleMarker>
        );
      })}
      {timeCursor == null && layers.bp.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        return (
          <CircleMarker key={`b${f.properties.side || ""}${f.properties.mmsi}`} center={[lat, lon]} radius={4}
            pathOptions={{ color: "#F8FAFC", fillColor: colorFor(f.properties.rank, f.properties.side), fillOpacity: 0.9, weight: 1, dashArray: "2,2", opacity: selected && selected !== f.properties.mmsi ? 0.2 : 0.9 }}>
            <Popup>Drift back-projection of slick centroid to closest approach of {f.properties.vessel_name || f.properties.mmsi}</Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
    </div>
  );
};

export const rankColor = rankColorFor;
