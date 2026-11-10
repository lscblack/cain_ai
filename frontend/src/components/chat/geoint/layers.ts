import { api } from "@/lib/api";

export type LayerDef = {
  id: string;
  kind: "base" | "overlay";
  label: string;
  url_template: string;
  attribution: string;
  dated: boolean;
  max_zoom: number;
};

const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";

// Keyless fallback so the map always has basemaps even if the API is down.
export const DEFAULT_LAYERS: LayerDef[] = [
  { id: "osm_dark", kind: "base", label: "Dark", url_template: OSM, attribution: "© OpenStreetMap contributors", dated: false, max_zoom: 19 },
  { id: "osm", kind: "base", label: "Streets", url_template: OSM, attribution: "© OpenStreetMap contributors", dated: false, max_zoom: 19 },
  { id: "esri_imagery", kind: "base", label: "Satellite", url_template: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attribution: "Imagery © Esri, Maxar, Earthstar Geographics", dated: false, max_zoom: 19 },
  { id: "esri_hillshade", kind: "overlay", label: "Hillshade", url_template: "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}", attribution: "© Esri", dated: false, max_zoom: 19 },
  { id: "gibs_modis_truecolor", kind: "base", label: "MODIS True Color", url_template: `${GIBS}/MODIS_Terra_CorrectedReflectance_TrueColor/default/{Time}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`, attribution: "NASA GIBS / EOSDIS", dated: true, max_zoom: 9 },
  { id: "gibs_viirs_truecolor", kind: "base", label: "VIIRS True Color", url_template: `${GIBS}/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{Time}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`, attribution: "NASA GIBS / EOSDIS", dated: true, max_zoom: 9 },
];

export async function fetchLayers(): Promise<LayerDef[]> {
  try {
    const r = await api.get<{ layers: LayerDef[] }>("/geoint/layers");
    return r?.layers?.length ? r.layers : DEFAULT_LAYERS;
  } catch {
    return DEFAULT_LAYERS;
  }
}

/** Resolve a layer's URL; dated layers get `date` (default yesterday, UTC) in {Time}. */
export function layerUrl(l: LayerDef, date?: string): string {
  return l.dated ? l.url_template.replace("{Time}", date || new Date(Date.now() - 86400000).toISOString().slice(0, 10)) : l.url_template;
}
