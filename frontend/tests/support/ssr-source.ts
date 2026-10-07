import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { Script } from 'node:vm';
import ts from 'typescript';

/** Playwright rewrites TSX as component descriptors. Compile a leaf source module
 * with TypeScript's real React runtime for static SSR only, without browser/effect claims. */
export function ssrSourceModule<T>(relativePath: string): T {
  if (!relativePath.startsWith('src/') || relativePath.includes('..')) throw new Error('SSR tests may read frontend source only.');
  const filename = path.resolve(process.env.UI_REVIEW_ROOT ?? process.cwd(), relativePath);
  const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), {
    fileName: filename,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const module = { exports: {} };
  const evaluate = new Script(`(function(require, module, exports) { ${compiled}\n})`, { filename }).runInThisContext() as (require: NodeJS.Require, module: { exports: unknown }, exports: unknown) => void;
  evaluate(createRequire(filename), module, module.exports);
  return module.exports as T;
}
