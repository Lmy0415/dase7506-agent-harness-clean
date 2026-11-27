"""Expose AppWorld's documented local APIs through two native function calls."""

import json
from pathlib import Path

from src.model import ROOT

DOCS = ROOT / '.appworld' / 'data' / 'api_docs' / 'standard'
SERVER_MANAGED = {
    'login', 'logout', 'signup', 'reset_password', 'send_password_reset_code',
    'verify_account', 'send_verification_code', 'show_account_passwords',
    'show_active_task',
}
RESPONSE_CHARS = 9000

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'find_api',
            'description': 'Find real AppWorld API names and parameter schemas. Use short keywords or an exact API name.',
            'parameters': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'app': {'type': 'string'}, 'query': {'type': 'string'}},
                'required': ['app'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'call_api',
            'description': 'Execute exactly one documented AppWorld API. The simulator handles login.',
            'parameters': {
                'type': 'object', 'additionalProperties': False,
                'properties': {
                    'app': {'type': 'string'}, 'api': {'type': 'string'},
                    'arguments': {'type': 'object'},
                },
                'required': ['app', 'api', 'arguments'],
            },
        },
    },
]


def _result(args, http, body, complete=False):
    return {'request': args, 'http_status': http, 'response': body, 'complete': complete}


def _json_body(response):
    try:
        return response.json()
    except (ValueError, AttributeError):
        return {'text': response.text}


def auth_app(parameter, default_app):
    if parameter == 'access_token':
        return default_app
    if parameter.endswith('_access_token'):
        return parameter.removesuffix('_access_token')
    return None


def for_model(result):
    # The trace retains the full simulator response. The model sees bounded output.
    visible = json.dumps({
        'http_status': result['http_status'],
        'response': result['response'],
    }, ensure_ascii=False, default=str)
    if len(visible) <= RESPONSE_CHARS:
        return visible
    return json.dumps({
        'http_status': result['http_status'],
        'partial_response': visible[:RESPONSE_CHARS],
        'hint': 'Response truncated. Narrow the query or use fewer results per page.',
    }, ensure_ascii=False)


class Simulator:
    def __init__(self, world, tokens=None):
        self.world = world
        self.tokens = dict(tokens or {})
        self.catalogue = {}
        for app in sorted(world.task.allowed_apps):
            if app == 'api_docs':
                continue
            raw = json.loads((DOCS / f'{app}.json').read_text())
            self.catalogue[app] = {key: value for key, value in raw.items() if key not in SERVER_MANAGED}

    def _find(self, app, query):
        terms = query.lower().replace('_', ' ').split()
        docs = self.catalogue.get(app)
        if docs is None:
            return {'error': 'Unknown app', 'available_apps': sorted(self.catalogue)}
        ranked = []
        for name, doc in docs.items():
            title = name.lower().replace('_', ' ')
            combined = f"{title} {doc['description'].lower()}"
            rank = (name == query, sum(word in title for word in terms), sum(word in combined for word in terms))
            if not terms or rank[-1]:
                ranked.append((rank, name))
        names = sorted(ranked, key=lambda item: (item[0], item[1]), reverse=True)
        if not names:
            return {'matches': [], 'hint': 'Try one keyword or omit query to list API names.'}
        if not terms:
            return {'api_names': sorted(docs)}
        matches = []
        for _, name in names[:5]:
            doc = docs[name]
            matches.append({
                'api': name, 'description': doc['description'],
                'parameters': [p for p in doc['parameters'] if not auth_app(p['name'], app)],
            })
        return {'matches': matches}

    def _token(self, app):
        if app not in self.tokens:
            profile = self.world.apis.supervisor.show_profile()
            passwords = self.world.apis.supervisor.show_account_passwords()
            password = next((p['password'] for p in passwords if p['account_name'] == app), None)
            if password is None:
                return None
            username = profile['phone_number' if app == 'phone' else 'email']
            reply = self.world.requester._request(
                app, 'login', username=username, password=password, raise_on_failure=False,
            )
            if reply.status_code != 200:
                return None
            self.tokens[app] = reply.json()['access_token']
        return self.tokens[app]

    def invoke(self, name, args, observe=None):
        if name == 'find_api' and set(args) <= {'app', 'query'} and isinstance(args.get('app'), str) and isinstance(args.get('query', ''), str):
            return _result(args, 200, self._find(args['app'], args.get('query', '')))
        if (name != 'call_api' or set(args) != {'app', 'api', 'arguments'}
                or not isinstance(args['app'], str) or not isinstance(args['api'], str)
                or not isinstance(args['arguments'], dict)):
            return _result(args, 400, {'error': 'Provide a valid function and JSON argument object.'})
        app, api, params = args['app'], args['api'], args['arguments']
        doc = self.catalogue.get(app, {}).get(api)
        if doc is None:
            return _result(args, 400, {'error': 'API unavailable. Use find_api.'})
        accepted = {p['name'] for p in doc['parameters'] if not auth_app(p['name'], app)}
        if not params.keys() <= accepted:
            return _result(args, 400, {'error': 'Unrecognized parameter. Use find_api for the schema.'})
        required = {p['name'] for p in doc['parameters'] if p['required'] and p['name'] in accepted}
        if not required <= params.keys():
            return _result(args, 400, {'error': f'Missing required parameters: {sorted(required - params.keys())}'})
        actual = dict(params)
        for param in doc['parameters']:
            login_app = auth_app(param['name'], app)
            if login_app in self.catalogue:
                token = self._token(login_app)
                if token is not None:
                    actual[param['name']] = token
                elif param['required']:
                    return _result(args, 401, {'error': 'This simulated account is unavailable.'})
        before = observe(self.world) if observe else None
        response = self.world.requester._request(app, api, raise_on_failure=False, **actual)
        code = response.status_code
        event = _result(args, code, _json_body(response), 200 <= code < 300 and (app, api) == ('supervisor', 'complete_task'))
        if observe:
            event['before'] = before
            event['after'] = observe(self.world)
        return event
