import assert from 'node:assert/strict';
import { chmod, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { getLiveBinary } from './live-harness.ts';

test('required live tests reject an absent, relative or missing executable', () => {
  assert.throws(() => getLiveBinary({ MEMCUE_REQUIRE_LIVE: '1' }), /MEMCUE_TEST_BINARY/);
  assert.throws(() => getLiveBinary({ MEMCUE_TEST_BINARY: './memcue' }), /absolute/);
  assert.throws(() => getLiveBinary({ MEMCUE_TEST_BINARY: join(tmpdir(), 'absent-memcue-fixture') }), /executable/);
  assert.equal(getLiveBinary({}), undefined);
});

test('live binary validation requires an executable file rather than a directory', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'memcue-live-config-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  assert.throws(() => getLiveBinary({ MEMCUE_TEST_BINARY: directory }), /executable/);
  const binary = join(directory, 'binary');
  await writeFile(binary, '#!/bin/sh\nexit 0\n', { mode: 0o600 });
  assert.throws(() => getLiveBinary({ MEMCUE_TEST_BINARY: binary }), /executable/);
  await chmod(binary, 0o700);
  assert.equal(getLiveBinary({ MEMCUE_TEST_BINARY: binary, MEMCUE_REQUIRE_LIVE: '1' }), binary);
});
