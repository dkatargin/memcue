"""Normal-plugin request bridge. Only an initialized active provider owns a base."""
import json
import os
import hashlib
import weakref


class _TransientContext(dict):
    """Dict-only wire format; deepcopy preserves the weak, non-serialized owner."""
    def __init__(self, payload, owner):
        super().__init__(payload)
        self._owner = weakref.ref(owner)



def request_context(request, session_id='', **kwargs):
    if not session_id:
        return None
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config
    from plugins.memory import load_memory_provider
    from agent.runtime_cwd import resolve_agent_cwd
    def enabled():
        config = load_config()
        plugins = config.get('plugins') or {}
        return ((config.get('memory') or {}).get('provider') == 'memcue' and
                'memcue-context' in (plugins.get('enabled') or []) and
                'memcue-context' not in (plugins.get('disabled') or []))
    if not enabled():
        return None
    home = os.path.realpath(str(get_hermes_home()))
    candidate = load_memory_provider('memcue')
    if candidate is None or not hasattr(type(candidate), 'request_owner'):
        return None
    owner = type(candidate).request_owner(home, session_id)
    if owner is None:
        return None
    key = 'input' if isinstance(request.get('input'), list) else 'messages'
    if not isinstance(request.get(key), list):
        return None
    ok, raw = owner._run(['session-card', '-pitfalls-json'],
                         stdin=json.dumps({'cwd':str(resolve_agent_cwd())}), timeout=10,
                         state_dir=os.path.join(owner._state, 'request-context', hashlib.sha256(os.path.abspath(owner._facts).encode()).hexdigest()[:16]))
    # I/O can outlive a switch/shutdown or policy change. Revalidate the capability before emission.
    if (os.path.realpath(str(get_hermes_home())) != home or
            type(candidate).request_owner(home, session_id) is not owner or not enabled()):
        return None
    text = 'Repository pitfalls unavailable; earlier snapshots do not establish current applicability.'
    if ok:
        try:
            snapshot = json.loads(raw)
            facts = snapshot['facts']
            if isinstance(facts, list) and all(isinstance(f, str) for f in facts):
                text = (snapshot.get('context') or 'No current repository pitfalls; this supersedes earlier snapshots.') + '\n\n' + '\n\n'.join(facts)
        except (ValueError, KeyError, TypeError):
            pass
    item = {'role':'developer', 'content':text}
    if key == 'input':
        item = {'type':'message','role':'developer','content':[{'type':'input_text','text':text}]}
    # The released dispatcher deep-copies requests. A weak owner attribute survives
    # those copies but dict/JSON serialization emits only provider-recognized keys.
    # Ordinary messages with identical content are never ownership evidence.
    messages = [message for message in request[key] if not (
        isinstance(message, _TransientContext) and message._owner() is owner)]
    return {'request':{**request,key:[*messages,_TransientContext(item, owner)]},'source':'memcue-context'}


def register(ctx):
    ctx.register_middleware('llm_request', request_context)
