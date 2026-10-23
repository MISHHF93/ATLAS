"use client";

import { useEffect, useState } from "react";
import type { Feature100Item } from "../components/shell/hundredFeaturesData";

// The backend (/api/features-100, src/atlas/proctoring_and_features100.py) is the source of truth
// for the 100-feature map. Nothing here is hard-coded.

type ApiFeature = {
  feature_id: string;
  feature_number: number;
  category_number: number;
  category_name: string;
  title: string;
  description: string;
  realm: string;
  subsystem: string;
  status: string;
  evidence?: string;
};

export type Features100State =
  | { phase: "loading"; rows: Feature100Item[] }
  | { phase: "error"; rows: Feature100Item[]; error: string }
  | { phase: "ready"; rows: Feature100Item[] };

function normalizeRealm(realm: string): Feature100Item["realm"] {
  const r = realm.toLowerCase();
  if (r.includes("both")) return "Both";
  if (r.includes("open")) return "Open-Market";
  return "Prop Competition";
}

export function toFeature100Item(f: ApiFeature): Feature100Item {
  return {
    featureId: f.feature_id,
    number: f.feature_number,
    categoryId: f.category_number,
    categoryTitle: f.category_name,
    name: f.title,
    realm: normalizeRealm(f.realm),
    subsystem: f.subsystem,
    description: f.description,
    status: f.status,
    evidence: f.evidence ?? "",
  };
}

export function useFeatures100(enabled: boolean, apiBase = ""): Features100State {
  const [state, setState] = useState<Features100State>({ phase: "loading", rows: [] });
  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    setState((s) => ({ phase: "loading", rows: s.rows }));
    fetch(`${apiBase}/api/features-100`, { cache: "no-store", signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { features?: ApiFeature[] };
        if (!Array.isArray(body.features)) throw new Error("Response has no features list");
        setState({ phase: "ready", rows: body.features.map(toFeature100Item) });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ phase: "error", rows: [], error: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [enabled, apiBase]);
  return state;
}
