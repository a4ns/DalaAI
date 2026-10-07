import { createRequire } from 'node:module';
import path from 'node:path';

/** UI_REVIEW_ROOT is an immutable checkout/archive of the exact reviewed commit. */
const requireSource = createRequire(path.join(process.cwd(), 'package.json'));
export function sourceModule<T>(relativePath: string): T {
  const root = process.env.UI_REVIEW_ROOT ?? process.cwd();
  if (!relativePath.startsWith('src/') || relativePath.includes('..')) {
    throw new Error('Independent tests may import frontend source only.');
  }
  return requireSource(path.resolve(root, relativePath)) as T;
}
