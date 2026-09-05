import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Polyline, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import { fmtTime } from "@/lib/api";

const RANK_COLORS = ["#FF2A6D", "#FFB703", "#00F0FF", "#9D4EDD", "#38BDF8", "#10B981"];
const colorFor = (rank) => RANK_COLORS[Math.min((rank || 1) - 1, RANK_COLORS.length - 1)];

const FitBounds = ({ geojson }) => {
  const map = useMap();
  useEffect(() => {
    if (!geojson?.features?.length) return;
    const layer = L.geoJSON(geojson);
    const b = layer.getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [24, 24] });
    setTimeout(() => map.invalidateSize(), 50);
  }, [geojson, map]);
  return null;
};

export const CaseMap = ({ geojson, selected, onSelect, showTracks = true, showCorridor = true }) => {
  const layers = useMemo(() => {
    const f = geojson?.features || [];
    return {
      spill: f.filter((x) => x.properties.layer === "spill"),
      corridor: f.filter((x) => x.properties.layer === "corridor"),
      tracks: f.filter((x) => x.properties.layer === "track"),
      fixes: f.filter((x) => x.properties.layer === "closest_fix"),
      bp: f.filter((x) => x.properties.layer === "backprojected_centroid"),
    };
  }, [geojson]);

  return (
    <div className="h-full w-full" data-testid="case-map">
    <MapContainer center={[53.5, 3.8]} zoom={9} className="h-full w-full" zoomControl>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; OpenStreetMap contributors' className="dark-tiles" />
      <FitBounds geojson={geojson} />
      {showCorridor && layers.corridor.map((f, i) => (
        <GeoJSON key={`c${i}`} data={f} style={{ color: "#00F0FF", weight: 1, dashArray: "6,6", fillColor: "#00F0FF", fillOpacity: 0.05 }} />
      ))}
      {layers.spill.map((f, i) => (
        <GeoJSON key={`s${i}-${f.properties.id}`} data={f} style={{ color: "#FF2A6D", weight: 2, dashArray: "4,4", fillColor: "#FF2A6D", fillOpacity: 0.35 }}>
          <Popup><b>Spill observation</b><br />Acquired {fmtTime(f.properties.acquisition_time)}<br />Confidence {Math.round(f.properties.detection_confidence * 100)}% · {f.properties.estimated_area_km2} km²<br />{f.properties.quality_flags?.join(", ") || "no quality flags"}</Popup>
        </GeoJSON>
      ))}
      {showTracks && layers.tracks.map((f) => {
        const p = f.properties;
        const dim = selected && selected !== p.mmsi;
        return (
          <Polyline key={`t${p.mmsi}`} positions={f.geometry.coordinates.map(([lon, lat]) => [lat, lon])}
            pathOptions={{ color: colorFor(p.rank), weight: dim ? 1.5 : 3, opacity: dim ? 0.3 : 0.85 }}
            eventHandlers={{ click: () => onSelect?.(p.mmsi) }} />
        );
      })}
      {layers.fixes.map((f) => {
        const p = f.properties;
        const [lon, lat] = f.geometry.coordinates;
        return (
          <CircleMarker key={`f${p.mmsi}`} center={[lat, lon]} radius={p.rank === 1 ? 8 : 6}
            pathOptions={{ color: colorFor(p.rank), fillColor: colorFor(p.rank), fillOpacity: selected === p.mmsi ? 1 : 0.7, weight: 2 }}
            eventHandlers={{ click: () => onSelect?.(p.mmsi) }}>
            <Popup>
              <b>#{p.rank} {p.vessel_name || p.mmsi}</b><br />MMSI {p.mmsi} · score {p.score?.toFixed(3)} · {p.status}<br />
              Closest approach {fmtTime(p.timestamp)}<br />{p.distance_km} km from slick · {p.time_gap_hours}h {p.time_gap_hours >= 0 ? "before" : "after"} acquisition<br />
              SOG {p.sog_kn ?? "—"} kn · COG {p.cog_deg ?? "—"}°
            </Popup>
          </CircleMarker>
        );
      })}
      {layers.bp.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        return (
          <CircleMarker key={`b${f.properties.mmsi}`} center={[lat, lon]} radius={4}
            pathOptions={{ color: "#F8FAFC", fillColor: colorFor(f.properties.rank), fillOpacity: 0.9, weight: 1, dashArray: "2,2", opacity: selected && selected !== f.properties.mmsi ? 0.2 : 0.9 }}>
            <Popup>Drift back-projection of slick centroid to closest approach of {f.properties.vessel_name || f.properties.mmsi}</Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
    </div>
  );
};

export const rankColor = colorFor;
