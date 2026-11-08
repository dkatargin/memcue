import assert from 'node:assert/strict'
import {test,mock} from 'node:test'
import {spawn,spawnSync} from 'node:child_process'
import {readFileSync} from 'node:fs'

const fixture=process.env.MEMCUE_RESPONSE_FIXTURE
if(fixture){
 const cfg=JSON.parse(readFileSync(fixture,'utf8'))
 Object.assign(process.env,cfg.native_env)
 let fault=''
 const calls=[]
 mock.module('node:child_process',{namedExports:{spawn:(binary,args,options)=>{
  const child=spawn(binary,args,options)
  if(options.env?.MEMCUE_OUTCOME_NONCE && fault){
   calls.push('correct')
   if(fault==='partial'){
    const on=child.stdout.on.bind(child.stdout)
    child.stdout.on=(event,cb)=>on(event,event==='data'?chunk=>cb(chunk.slice(0,5)):cb)
   } else if(fault==='timeout'){
    const on=child.on.bind(child)
    child.on=(event,cb)=>on(event,event==='close'?code=>setTimeout(()=>cb(code),16000).unref():cb)
   } else child.stdout.destroy()
  }
  return child
 }}})
 const {apply}=await import('../src/index.mjs')
 test('real DSH caller classifies committed response loss as unknown without replay',async(t)=>{
  const tools=new Map();apply({on:()=>()=>{},tools:{register:t=>{tools.set(t.name,t);return()=>{}}},systemPrompt:{section:()=>()=>{}}},{binary:cfg.binary,facts:cfg.binary+'.absent'})
  const exec={agent:{session:{header:{cwd:process.cwd()}}}}
  const call=(name,args)=>tools.get(name).execute(args,exec)
  for(const mode of ['partial','closed','timeout']) await t.test(mode,async()=>{
   const added=await call('memcue_add',{text:'Prefer concise reviews with useful examples.',kind:'rule',source:'user'})
   assert.equal(added.stored,true)
   const psql=(query)=>{
    const r=spawnSync(cfg.psql,['-XAt','-c',query],{env:{...process.env,...cfg.psql_env},encoding:'utf8'})
    assert.equal(r.status,0);return r.stdout.trim()
   }
   const id=psql('SELECT id FROM memcue.facts ORDER BY id DESC LIMIT 1')
   fault=mode
   const answer=await call('memcue_correct',{id,expected_version:1,text:'Prefer concise reviews with concrete useful examples.'})
   fault=''
   assert.equal(psql(`SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='${id}'`),'1,2')
   assert.match(answer.message,/UNKNOWN OUTCOME|ambiguous/i,`${mode}: committed mutation must be explicitly unknown`)
   assert.notEqual(answer.stored,true)
   assert.match(answer.message,/history/)
   assert.ok(answer.message.includes(id))
   assert.ok(!answer.message.includes(cfg.password))
  })
  assert.deepEqual(calls,['correct','correct','correct'])
 })
 test('unknown delivery does not claim the durable change was unwritten',async()=>{
  const tools=new Map();apply({on:()=>()=>{},tools:{register:t=>{tools.set(t.name,t);return()=>{}}},systemPrompt:{section:()=>()=>{}}},{binary:cfg.binary,facts:cfg.binary+'.absent'})
  const exec={agent:{session:{header:{cwd:process.cwd()}}}}
  const added=await tools.get('memcue_add').execute({text:'Prefer clear review explanations.',kind:'rule',source:'user'},exec)
  const id=added.message.match(/[0-9A-HJKMNP-TV-Z]{26}/)[0]
  fault='partial'
  const answer=await tools.get('memcue_correct').execute({id,expected_version:1,text:'Prefer clear concrete review explanations.'},exec)
  fault=''
  assert.match(answer.message,/UNKNOWN OUTCOME/)
  assert.equal(answer.stored,null,'unknown storage outcome must not claim stored=false')
  assert.equal(answer.outcome,'unknown')
 })
 test('complete receipt for an existing string ID is successful',async()=>{
  const tools=new Map();apply({on:()=>()=>{},tools:{register:t=>{tools.set(t.name,t);return()=>{}}},systemPrompt:{section:()=>()=>{}}},{binary:cfg.binary,facts:cfg.binary+'.absent'})
  const exec={agent:{session:{header:{cwd:process.cwd()}}}}
  const added=await tools.get('memcue_add').execute({text:'Prefer truthful receipt classifications.',kind:'rule',source:'user'},exec)
  const generated=added.message.match(/[0-9A-HJKMNP-TV-Z]{26}/)[0]
  const sql=q=>{const r=spawnSync(cfg.psql,['-XAt','-v','ON_ERROR_STOP=1','-c',q],{env:{...process.env,...cfg.psql_env},encoding:'utf8'});assert.equal(r.status,0);return r.stdout.trim()}
  sql(`UPDATE memcue.facts SET id='legacy-dsh',payload=jsonb_set(payload,'{ID}',to_jsonb('legacy-dsh'::text)) WHERE id='${generated}'`)
  const answer=await tools.get('memcue_correct').execute({id:'legacy-dsh',expected_version:1,text:'Prefer truthful complete receipt classifications.'},exec)
  assert.equal(sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='legacy-dsh'"),'1,2')
  assert.equal(answer.stored,true,'complete native receipt for existing ID must remain successful')
 })
}else test('requires isolated native PostgreSQL fixture', {skip:true},()=>{})
