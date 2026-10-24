import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import ts from "typescript";
const out = ts.transpileModule(readFileSync("src/components/shell/pagesMap.ts", "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const m = {}; new Function("exports", out)(m);
for (const p of m.PAGES) for (const a of [...(p.aliases ?? []), ...(p.tabs ?? []).flatMap(t => t.aliases ?? [])]) {
  const dir = "app" + a; mkdirSync(dir, { recursive: true });
  writeFileSync(dir + "/page.tsx", `import { redirect } from "next/navigation";\n\n/** Former address, kept working: opens the hub tab that now holds this content. */\nexport default function LegacyPage() {\n  redirect("${m.redirectTarget(a)}");\n}\n`);
  console.log(a, "->", m.redirectTarget(a));
}
