#!/usr/bin/env python3
"""Run the existing memcue CLI with one explicit Codex configuration."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 4 * 1024 * 1024
INPUT_LIMIT = 64 * 1024
TIMEOUT = 15


class AdapterError(Exception):
    """A failure the caller can report without stopping Codex."""


def bounded(text):
    return ' '.join(str(text).split())[:600]


def load_config(path):
    if not path.is_absolute():
        raise AdapterError('configuration path must be absolute')
    with path.open('rb') as f:
        data = f.read(INPUT_LIMIT + 1)
    if len(data) > INPUT_LIMIT:
        raise AdapterError('configuration exceeds 64 KiB')
    config = json.loads(data)
    allowed = {'binary', 'facts', 'state_dir', 'host', 'background_dream', 'dream_every'}
    if not isinstance(config, dict) or config.keys() - allowed:
        raise AdapterError('configuration must be an object with documented keys only')
    for key in ('binary', 'facts', 'state_dir'):
        value = config.get(key)
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise AdapterError(key + ' must be an absolute path')
    if not Path(config['binary']).is_file() or not os.access(config['binary'], os.X_OK):
        raise AdapterError('configured memcue binary is missing or not executable')
    host = config.get('host')
    if not isinstance(host, str) or not host or any(c.isspace() for c in host):
        raise AdapterError('host must be an explicit nonempty name without whitespace')
    if config.get('background_dream', False) is not False:
        raise AdapterError('background_dream must be false; this adapter uses model-driven dream only')
    if 'dream_every' in config and (not isinstance(config['dream_every'], str) or not config['dream_every']):
        raise AdapterError('dream_every must be a nonempty Go duration, for example 24h')
    return config


def child_env(config):
    env = {k: v for k, v in os.environ.items() if not k.startswith('MEMCUE_')}
    env.update(MEMCUE_FACTS=config['facts'], MEMCUE_STATE_DIR=config['state_dir'],
               MEMCUE_HOST=config['host'], MEMCUE_DREAM_BACKGROUND='0')
    if 'dream_every' in config:
        env['MEMCUE_DREAM_EVERY'] = config['dream_every']
    return env


def call(config, args, cwd, data='', timeout=TIMEOUT):
    # Files avoid unbounded in-memory capture from a broken binary. Time and read size are bounded.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run([config['binary'], *args], input=data.encode(), stdout=out, stderr=err,
                                    cwd=cwd, env=child_env(config), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdapterError('memcue command timed out; check persisted state before retrying a write') from exc
        out.seek(0)
        output = out.read(LIMIT + 1)
        err.seek(0)
        diagnostic = err.read(2400).decode('utf-8', errors='replace')
        if result.returncode:
            raise AdapterError('memcue command failed (exit ' + str(result.returncode) + '): ' + bounded(diagnostic))
        if len(output) > LIMIT:
            raise AdapterError('memcue output exceeds 4 MiB; narrow the request')
        return output.decode('utf-8')


def hook_input():
    raw = sys.stdin.buffer.read(INPUT_LIMIT + 1)
    if len(raw) > INPUT_LIMIT:
        raise AdapterError('hook input exceeds 64 KiB')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('hook_event_name') != 'SessionStart':
        raise AdapterError('expected SessionStart hook input')
    if data.get('source') not in ('startup', 'resume', 'clear', 'compact', 'fork'):
        raise AdapterError('unsupported SessionStart source')
    for key in ('session_id', 'cwd', 'model', 'permission_mode'):
        if not isinstance(data.get(key), str) or not data[key]:
            raise AdapterError('hook input needs ' + key)
    if data['permission_mode'] not in ('default', 'acceptEdits', 'plan', 'dontAsk', 'bypassPermissions'):
        raise AdapterError('invalid permission_mode')
    if 'transcript_path' not in data or not (data['transcript_path'] is None or isinstance(data['transcript_path'], str)):
        raise AdapterError('hook input needs nullable transcript_path')
    cwd = Path(data['cwd'])
    if not cwd.is_absolute() or not cwd.is_dir():
        raise AdapterError('hook cwd must name an existing absolute directory')
    return data


def context(command):
    return (ROOT / 'policy.md').read_text(encoding='utf-8').replace('@MEMCUE@', command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = os.environ.get('MEMCUE_CODEX_CONFIG') or str(Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'memcue.json')
    parser.add_argument('--config', default=default, help='absolute path to memcue JSON configuration')
    parser.add_argument('command')
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    hook = args.command == 'hook'
    response = {}
    try:
        config_path = Path(args.config)
        config = load_config(config_path)
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), '--config', str(config_path)])
        if hook:
            response['hookSpecificOutput'] = {'hookEventName': 'SessionStart', 'additionalContext': context(command)}
            data = hook_input()
            call(config, ['version', '-minimum', '0.30.0'], data['cwd'], timeout=5)
            card = call(config, ['session-card', '-dream-tools'], data['cwd'], json.dumps(data), timeout=10)
            if card.strip():
                output = json.loads(card)['hookSpecificOutput']
                if not isinstance(output, dict) or output.get('hookEventName') != 'SessionCard' or not isinstance(output.get('additionalContext'), str):
                    raise AdapterError('invalid memcue SessionCard response')
                hints = output['additionalContext'].replace(
                    'call memcue_dream_prepare and answer its packet with memcue_dream_apply',
                    'run the memcue-dream skill with the configured launcher')
                response['hookSpecificOutput']['additionalContext'] += '\n\n' + hints
        elif args.command == 'instructions':
            sys.stdout.write((ROOT / 'AGENTS.md.snippet').read_text(encoding='utf-8').replace(
                '@MEMCUE@', command).replace('@ROOT@', str(ROOT)))
        else:
            if args.command not in ('version', 'search', 'add', 'correct', 'retire', 'reopen', 'facts', 'dump', 'dream'):
                raise AdapterError('unsupported command; use search/add/correct/retire/reopen/facts/dump/version/dream')
            if args.command == 'dream' and not (args.args in (['-prepare'], ['-prepare', '-all'], ['-list']) or
                                                len(args.args) == 3 and args.args[:2] == ['-prepare', '-since'] and
                                                args.args[2] and not args.args[2].startswith('-') or
                                                len(args.args) == 2 and args.args[0] == '-apply'):
                raise AdapterError('dream accepts only -prepare [-all | -since DATE], -list or -apply FILE; no background runner')
            call(config, ['version', '-minimum', '0.30.0'], os.getcwd())
            sys.stdout.write(call(config, [args.command, *args.args], os.getcwd(), timeout=60 if args.command == 'dream' else TIMEOUT))
    except (AdapterError, OSError, ValueError, KeyError, TypeError) as exc:
        message = 'memcue (Codex): ' + bounded(exc) + '. Other Codex work can continue.'
        print(message, file=sys.stderr)
        if not hook:
            return 1
        response['systemMessage'] = message
    if hook:
        print(json.dumps(response))
    return 0


if __name__ == '__main__':
    sys.exit(main())
