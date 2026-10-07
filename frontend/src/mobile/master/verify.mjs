// Isolated-lane check, not an integration or live API test.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const lane = dirname(fileURLToPath(import.meta.url));
const shared = process.argv[2] && resolve(process.argv[2]);
if (!shared) throw new Error('Pass the B4 frontend directory containing shared source and installed dependencies.');
const directory = resolve(lane, '.verification');
mkdirSync(directory, { recursive: true });
const config = {
  compilerOptions: {
    target: 'ES2023', lib: ['ES2023', 'DOM', 'DOM.Iterable'], strict: true,
    module: 'ESNext', moduleResolution: 'Bundler', jsx: 'react-jsx', noEmit: true,
    skipLibCheck: true, noUnusedLocals: true, noUnusedParameters: true, verbatimModuleSyntax: true,
    rootDirs: [resolve(lane, '../..'), resolve(shared, 'src')],
    paths: {
      react: [resolve(shared, 'node_modules/@types/react/index.d.ts')],
      'react/jsx-runtime': [resolve(shared, 'node_modules/@types/react/jsx-runtime.d.ts')],
    },
  },
  include: [resolve(lane, 'MasterScreen.tsx'), resolve(lane, 'types.ts'), resolve(lane, 'masterModel.ts'), resolve(shared, 'node_modules/vite/client.d.ts')],
};
const configPath = resolve(directory, 'tsconfig.json');
writeFileSync(configPath, JSON.stringify(config, null, 2));
const checks = [
  [process.execPath, [resolve(shared, 'node_modules/typescript/bin/tsc'), '--project', configPath]],
  [resolve(shared, 'node_modules/.bin/oxlint'), ['--config', resolve(shared, '.oxlintrc.json'), '--deny-warnings', lane]],
  [process.execPath, ['--test', resolve(lane, 'masterModel.test.mjs'), resolve(lane, 'renderSmoke.test.mjs')]],
];
for (const [command, args] of checks) {
  const result = spawnSync(command, args, { stdio: 'inherit', env: { ...process.env, MASTER_SHARED_FRONTEND: shared } });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
