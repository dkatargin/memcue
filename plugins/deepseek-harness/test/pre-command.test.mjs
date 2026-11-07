import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { apply } from '../src/index.mjs'

test('real CLI packet through the DSH tool keeps target scope, budget and repeat suppression', async () => {
 const root = await mkdtemp(join(tmpdir(), 'memcue-pre-command-'))
 const oldState = process.env.MEMCUE_STATE_DIR
 try {
  const repo = join(root, 'orchard')
  await mkdir(join(repo, '.git'), { recursive: true })
  await writeFile(join(repo, '.git/config'), '[remote "origin"]\nurl = https://synthetic.invalid/orchard.git\n')
  process.env.MEMCUE_STATE_DIR = join(root, 'state')
  const binary = process.env.MEMCUE_BIN || resolve('bin/memcue')
  const facts = join(root, 'facts')
  const added = spawnSync(binary, ['add', '-cwd', repo, '-kind', 'pitfall', '-scope', 'repo', '--', 'Orchard build requires amber mode only for synthetic fixtures.'], { env: { ...process.env, MEMCUE_FACTS: facts, MEMCUE_API_URL: '', MEMCUE_API_KEY: '' }, encoding: 'utf8' })
  assert.equal(added.status, 0, added.stderr)
  const id = added.stdout.trim().split(/\s+/)[0]
  const tools = new Map()
  let note = ''
  apply({ on() {}, tools: { register(tool) { tools.set(tool.name, tool) } }, systemPrompt: { section(section) { note = section.text } } }, { binary, facts })
  const tool = tools.get('memcue_pre_command')
  const instruction = note.split('\n').find(line => line.startsWith('- Before the first relevant command'))
  assert.ok(instruction)
  assert.ok(Buffer.byteLength(instruction + JSON.stringify({ name: tool.name, description: tool.description, parameters: tool.parameters, output: tool.output.schema })) <= 2048)
  const args = { cwd: repo, session: 'synthetic-task', action: 'build', query: 'orchard build' }
  const first = await tool.execute(args)
  assert.ok(Buffer.byteLength(first.packet) <= 4096)
  assert.deepEqual(tool.output.render(args, first), [{ type: 'text', text: first.packet }])
  assert.equal(JSON.parse(first.packet).facts[0].id, id)
  assert.equal(JSON.parse(first.packet).blocked, true)
  const replay = JSON.parse((await tool.execute(args)).packet)
  assert.deepEqual(replay.facts, JSON.parse(first.packet).facts)
  const ready = JSON.parse((await tool.execute({ ...args, ack: replay.receipt })).packet)
  assert.equal(ready.blocked, false)
  assert.deepEqual(JSON.parse((await tool.execute(args)).packet).facts, [])
  assert.ok(JSON.parse((await tool.execute({ ...args, epoch: 'compact-1' })).packet).facts.length)
  await assert.rejects(tool.execute({ ...args, cwd: '' }), /cwd is required/)
 } finally {
  if (oldState === undefined) delete process.env.MEMCUE_STATE_DIR
  else process.env.MEMCUE_STATE_DIR = oldState
  await rm(root, { recursive: true, force: true })
 }
})
