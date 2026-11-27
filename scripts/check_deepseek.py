"""Request one native tool call through the same budget ledger as the experiments."""

import json

from src.model import complete


def main():
    tool = 'verify_connection'
    response = complete(
        [{'role': 'user', 'content': 'Call verify_connection with the code ready.'}],
        purpose='stage0_connectivity', max_tokens=64,
        tools=[{'type': 'function', 'function': {
            'name': tool,
            'description': 'Return a fixed connectivity code for a local test.',
            'parameters': {
                'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code'],
            },
        }}],
        tool_choice={'type': 'function', 'function': {'name': tool}},
    )
    calls = response['choices'][0]['message'].get('tool_calls') or []
    if len(calls) != 1 or calls[0]['function']['name'] != tool:
        raise RuntimeError('The API responded without the expected native tool call.')
    if json.loads(calls[0]['function']['arguments']) != {'code': 'ready'}:
        raise RuntimeError('The native tool call did not contain the expected verification code.')
    print(json.dumps({'tool_call_verified': True, 'model': response['model'], 'usage': response['usage']}))


if __name__ == '__main__':
    main()
