// Copy check: every run of four or more words of prose in the Next app's components must appear, word for word, in
// the Vue app's source. A heuristic, not a parser: it reads text, so a phrase that the Vue template builds from two
// pieces is reported and has to be looked at by hand (the known ones are listed in ALLOWED with the reason).
//
//   npm run check:copy        exits 1 if a phrase is missing
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const NEXT = join(here, "../../frontend/src");
const VUE = join(here, "../src");

/** Phrases that differ on purpose. */
const ALLOWED = [
  // The Unreachable screen names the setting that points the app at the API; the Vue app's is VITE_API_TARGET.
  "To point this app at another address, set",
  // Built from two pieces in lib/analyst.ts (originLabel), so a table's row count can sit in the middle.
  "Typed, differs from the workbook",
  // Next-only: a note for pages rendered without scripts. The Vue app is a single-page app and has no such render.
  "Without scripts the blocks would stay at their starting opacity, so show them as they are.",
];

const walk = (dir, exts) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name), exts) : exts.some((x) => e.name.endsWith(x)) && !e.name.endsWith(".test.ts") ? [join(dir, e.name)] : [],
  );

const squash = (text) => text.replace(/\s+/g, " ");
/** Comments say how the code works, not what the person reads. */
const noComments = (text) =>
  text
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/(^|\s)\/\/[^\n]*/g, " ");

const WORD = "[A-Za-z0-9’“”‘…·,.:;!?()'%/&-]+";
const PHRASE = new RegExp(`${WORD}(?: ${WORD}){3,}`, "g");
/** A run of words that is code, not copy: class lists, identifiers, type annotations, expressions. */
const looksLikeCode = (p) =>
  /[a-z][A-Z]|&&|\|\||=>|\);|\) \{|if \(|\(\)|\?\.|\b(return|const|import|export|function|await|typeof|keyof)\b/.test(p) ||
  /\b[a-z]+: -?\d|: (string|number|boolean|void)\b|\w\.\w+\(|[a-z]\.[a-z]|: [A-Z]+,/.test(p) ||
  /(^|\s)(flex|grid|inline-flex|relative|absolute|sticky|fixed|hidden|block)(\s|$)|[a-z]+-\[|(^|\s)(px|py|pt|pb|gap|text|border|rounded|space-y|max-w|min-w|size|font)-/.test(p) ||
  p.split(" ").some((t) => /^[?:()!;]+$/.test(t)) ||
  p.split(" ").every((t) => /^[\d.,-]+$/.test(t));

const vue = squash([...walk(VUE, [".vue", ".ts"]), join(VUE, "../index.html")].map((f) => readFileSync(f, "utf8")).join("\n"));
const missing = [];
let checked = 0;
for (const file of walk(join(NEXT, "components"), [".tsx"]).concat(walk(join(NEXT, "app"), [".tsx"]))) {
  const text = squash(noComments(readFileSync(file, "utf8"))).replaceAll("&apos;", "'");
  for (const phrase of text.match(PHRASE) ?? []) {
    const p = phrase.replace(/^[(:;,.]+\s*|\s*[(:]+$/g, "").trim();
    if (p.split(" ").length < 4 || looksLikeCode(p) || ALLOWED.some((a) => p.includes(a) || a.includes(p))) continue;
    checked++;
    if (!vue.includes(p)) missing.push(`${file.slice(NEXT.length + 1).replaceAll("\\", "/")}: ${p}`);
  }
}
console.log(`${checked} phrases checked, ${missing.length} not found in frontend-vue/src`);
for (const m of missing) console.log("  " + m);
process.exit(missing.length ? 1 : 0);
