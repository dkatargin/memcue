import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { accessSync, constants, statSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import type { TestContext } from 'node:test';
import { MemcueCli, type CliResult } from '../src/cli.ts';
import { piFixture } from './pi-harness.ts';

export function getLiveBinary(env: NodeJS.ProcessEnv = process.env): string | undefined {
  const binary = env.MEMCUE_TEST_BINARY;
  if (!binary) {
    if (env.MEMCUE_REQUIRE_LIVE === '1') throw new Error('MEMCUE_TEST_BINARY is required for live tests.');
    return undefined;
  }
  if (!isAbsolute(binary)) throw new Error('MEMCUE_TEST_BINARY must be an absolute executable path.');
  try {
    assert.ok(statSync(binary).isFile());
    accessSync(binary, constants.X_OK);
  } catch {
    throw new Error('MEMCUE_TEST_BINARY must name an existing executable file.');
  }
  return binary;
}

export async function liveFixture(t: TestContext) {
  const binary = getLiveBinary();
  assert.ok(binary, 'a live fixture requires MEMCUE_TEST_BINARY');
  const inherited = new Map<string, string>();
  for (const [name, value] of Object.entries(process.env)) {
    if (value !== undefined && (name === 'MEMCUE_SERVER' || name === 'MEMCUE_POSTGRES_DSN'
      || name.startsWith('MEMCUE_TAILSCALE_'))) {
      inherited.set(name, value);
      delete process.env[name];
    }
  }
  t.after(() => { for (const [name, value] of inherited) process.env[name] = value; });
  const fixture = await piFixture();
  t.after(() => fixture.dispose());
  const repo = fixture.cwd;
  const other = join(fixture.root, 'other-repo');
  const plain = join(fixture.root, 'not-a-repo');
  await mkdir(plain);
  for (const [path, name] of [[repo, 'memcue-pi'], [other, 'other-project']]) {
    execFileSync('git', ['init', '-q', path], { stdio: 'pipe' });
    execFileSync('git', ['-C', path, 'remote', 'add', 'origin', `https://example.com/test/${name}.git`], { stdio: 'pipe' });
  }
  const cli = new MemcueCli({ binary, facts: fixture.facts, stateDir: fixture.stateDir, host: 'pi-test-host' });
  const run = (args: string[], mutation = false) => cli.run(args, { cwd: repo, mutation });
  return { ...fixture, binary, dir: fixture.root, repo, other, plain, cli, run };
}

export function successful(result: CliResult, mutation = false): string {
  assert.equal(result.exitCode, 0, JSON.stringify(result));
  assert.equal(result.outcome, mutation ? 'committed' : 'read', JSON.stringify(result));
  return result.stdout;
}
