// Invocation-owned group anchor. The actual executable inherits the parent's
// pipes directly. Remain alive after reaping it until asked to stop the group;
// signalling our own group here cannot race a reused PID in the caller.
import {spawn} from 'node:child_process'
let started=false,child
function stop(){
 if(process.platform==='win32'){child?.kill('SIGKILL');process.exit(1)}
 process.kill(-process.pid,'SIGKILL')
}
process.on('message',message=>{
 if(message.stop){stop();return}
 if(started)return
 started=true
 try{
  child=spawn(message.binary,message.args,{stdio:['inherit','inherit','inherit']})
  child.once('error',()=>process.send?.({spawnError:true}))
  child.once('exit',(code,signal)=>process.send?.({result:true,code,signal}))
 }catch{process.send?.({spawnError:true})}
})
process.on('disconnect',stop)
process.send?.({ready:true})
