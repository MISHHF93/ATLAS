"use client";

import { useEffect, useState } from "react";
import { AppNav } from "./AppNav";

type SpecDoc = {
  doc_id: string;
  title: string;
  path: string;
  content: string;
};

export function DocsReader() {
  const [docs, setDocs] = useState<SpecDoc[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("Reading the specification files.");

  useEffect(() => {
    let live = true;
    const pull = async () => {
      try {
        const response = await fetch("/api/docs", { cache: "no-store" });
        if (!response.ok) throw new Error(`Documentation returned HTTP ${response.status}`);
        const body = (await response.json()) as { documents?: SpecDoc[]; execution_permission?: string };
        if (!live) return;
        const documents = body.documents ?? [];
        setDocs(documents);
        setSelectedId((current) => current ?? documents[0]?.doc_id ?? null);
        setNote(`${documents.length} files · permission ${body.execution_permission ?? "none"}`);
      } catch (error) {
        if (!live) return;
        setNote(error instanceof Error ? error.message : "Documentation failed to load.");
      }
    };
    void pull();
    return () => {
      live = false;
    };
  }, []);

  const selected = docs.find((doc) => doc.doc_id === selectedId) ?? docs[0];

  return (
    <div className="atlas-app">
      <AppNav />
      <main className="docs-shell">
        <aside className="docs-index" aria-label="Specification files">
          <p className="docs-note">{note}</p>
          {docs.map((doc) => (
            <button
              key={doc.doc_id}
              type="button"
              className={doc.doc_id === selected?.doc_id ? "is-on" : undefined}
              onClick={() => setSelectedId(doc.doc_id)}
            >
              <strong>{doc.title}</strong>
              <span>{doc.path}</span>
            </button>
          ))}
        </aside>
        <article className="docs-body">
          {selected ? (
            <>
              <h1>{selected.title}</h1>
              <p className="docs-note">{selected.path}</p>
              <pre>{selected.content}</pre>
            </>
          ) : (
            <p className="docs-note">{note}</p>
          )}
        </article>
      </main>
    </div>
  );
}
