import { API_BASE } from "@/lib/api";

export interface GeoPoint { lat: number; lon: number; label?: string; kind?: string; distKm?: number }

/** Great-circle distance in km between two points. */
export function haversineKm(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLon = ((b.lon - a.lon) * Math.PI) / 180;
  const la1 = (a.lat * Math.PI) / 180;
  const la2 = (b.lat * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export interface Amenity { amenity: string; label: string }

// Map category words in a query to an OSM amenity tag.
const AMENITY_MATCHERS: { any: string[]; amenity: string; label: string }[] = [
  { any: ["hospital", "hosp", "hosti", "clinic", "emergency"], amenity: "hospital", label: "Hospitals" },
  { any: ["police"], amenity: "police", label: "Police" },
  { any: ["pharmacy", "pharmac", "chemist", "drug store", "drugstore"], amenity: "pharmacy", label: "Pharmacy" },
  { any: ["fuel", "gas station", "petrol", "gas"], amenity: "fuel", label: "Fuel" },
  { any: ["atm", "bank"], amenity: "bank", label: "ATM/Bank" },
  { any: ["restaurant", "food", "eat", "diner"], amenity: "restaurant", label: "Food" },
  { any: ["school", "college"], amenity: "school", label: "Schools" },
  { any: ["hotel", "lodge", "motel"], amenity: "hotel", label: "Hotels" },
  { any: ["supermarket", "grocery", "market"], amenity: "supermarket", label: "Supermarkets" },
  { any: ["cafe", "coffee"], amenity: "cafe", label: "Cafés" },
];

const NEAR_ME_RE = /\b(near|around|close to|next to|by)\s+(me|here|my\s+location|us)\b|nearby|closest|nearest/i;

export interface MapQuery { amenity?: Amenity; nearMe: boolean }

/** Parse a maps.find query for an amenity category and a "near me" intent. */
export function parseMapQuery(query: string): MapQuery {
  const q = (query || "").toLowerCase();
  const nearMe = NEAR_ME_RE.test(q);
  for (const m of AMENITY_MATCHERS) {
    if (m.any.some((w) => q.includes(w))) return { amenity: { amenity: m.amenity, label: m.label }, nearMe };
  }
  return { nearMe };
}

const LAT_KEYS = ["lat", "latitude"];
const LON_KEYS = ["lon", "lng", "long", "longitude"];

function toNum(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}
const okLat = (n: number) => n >= -90 && n <= 90;
const okLon = (n: number) => n >= -180 && n <= 180;

/** Recursively pull {lat,lon} pairs out of an arbitrary tool result. Only pairs
 * found on the SAME object are kept (so unrelated numbers aren't matched), and
 * values must sit inside valid coordinate ranges. */
export function findGeoPoints(root: unknown): GeoPoint[] {
  const out: GeoPoint[] = [];
  const seen = new Set<string>();
  const visit = (o: any) => {
    if (!o || typeof o !== "object") return;
    if (Array.isArray(o)) { o.forEach(visit); return; }
    let lat: number | null = null, lon: number | null = null;
    for (const k of Object.keys(o)) {
      const lk = k.toLowerCase();
      if (lat === null && LAT_KEYS.includes(lk)) { const n = toNum(o[k]); if (n !== null && okLat(n)) lat = n; }
      if (lon === null && LON_KEYS.includes(lk)) { const n = toNum(o[k]); if (n !== null && okLon(n)) lon = n; }
    }
    if ((lat === null || lon === null) && typeof o.loc === "string" && o.loc.includes(",")) {
      const [a, b] = o.loc.split(",").map((x: string) => Number(x.trim()));
      if (Number.isFinite(a) && Number.isFinite(b) && okLat(a) && okLon(b)) { lat = a; lon = b; }
    }
    if (lat !== null && lon !== null) {
      const key = `${lat.toFixed(5)},${lon.toFixed(5)}`;
      if (!seen.has(key)) {
        seen.add(key);
        out.push({ lat, lon, label: o.label || o.name || o.city || o.title || o.display_name, kind: o.type || o.kind });
      }
    }
    for (const k of Object.keys(o)) visit(o[k]);
  };
  visit(root);
  return out.slice(0, 60);
}

/** Geo points worth drawing a map for, scoped to a tool result's payload. */
export function toolGeoPoints(r: any): GeoPoint[] {
  if (!r || r.ok === false) return [];
  return findGeoPoints(r.result ?? r.places ?? r.points ?? r);
}

/** Human-readable byte size. */
export function humanSize(n?: number): string {
  if (!n || n < 1024) return `${n ?? 0} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Download a KAI-produced workspace file. The download endpoint needs the auth
 * header, so we fetch with the token and save the blob (a plain link can't). */
export async function downloadKaiFile(f: { download_url: string; name: string }) {
  const token = localStorage.getItem("kai.token");
  const resp = await fetch(`${API_BASE}${f.download_url}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) return;
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = f.name;
  a.click();
  URL.revokeObjectURL(a.href);
}
