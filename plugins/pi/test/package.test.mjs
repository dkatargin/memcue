import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const manifest = async path => JSON.parse(await readFile(new URL(path, root), 'utf8'));

test('the standalone Pi package carries the release version and public entrypoint', async () => {
  const pkg = await manifest('package.json');
  const rootPackage = JSON.parse(await readFile(new URL('../../package.json', root), 'utf8'));
  assert.equal(pkg.version, rootPackage.version);
  assert.equal(pkg.private, undefined);
  assert.equal(pkg.publishConfig?.access, 'public');
  assert.deepEqual(pkg.pi?.extensions, ['./index.ts']);
  for (const peer of ['@earendil-works/pi-coding-agent', 'typebox']) {
    assert.equal(pkg.peerDependencies?.[peer], '*');
    assert.equal(pkg.dependencies?.[peer], undefined);
  }
});

test('the distributed package includes every Pi runtime entrypoint and module', () => {
  const packed = JSON.parse(execFileSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], {
    cwd: fileURLToPath(root), encoding: 'utf8', timeout: 30_000,
  }));
  const files = new Set(packed[0].files.map(file => file.path));
  for (const path of ['index.ts', 'src/cli.ts', 'src/config.ts', 'src/extension.ts', 'src/install.ts',
    'src/instructions.ts', 'src/tools.ts', 'children/worker.ts', 'children/scout.ts', 'package.json']) {
    assert.ok(files.has(path), `missing packaged runtime: ${path}`);
  }
});
