"""Start the local UI only after a credential-free provider connectivity check.

Run from a normal terminal. --check-only sends one unauthenticated GET to the
configured provider's /models route; it never sends an API key or model request.
An HTTP response proves network reachability, not valid credentials/model output.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def _without_auth(request):
    # A truthy auth callback suppresses requests' implicit .netrc credentials
    # while retaining proxy/CA environment settings used by the real service.
    request.headers.pop('Authorization', None)
    return request


def probe_provider(base_url):
    result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'network_reachable': False, 'authorization_sent': False, 'model_request_verified': False}
    try:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('invalid provider URL')
        endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/')+'/models', '', ''))
        response = requests.get(endpoint, timeout=8, allow_redirects=False, auth=_without_auth)
        result.update(network_reachable=True, http_status=response.status_code)
    except (requests.RequestException, ValueError) as error:
        result['error_code'] = ('network_permission_denied' if '10013' in str(error)
                                else 'invalid_provider_url' if isinstance(error, ValueError)
                                else 'provider_connection_failed')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--port', type=int, default=8010)
    args = parser.parse_args(argv)
    load_dotenv(ROOT/'.env', override=True)
    result = probe_provider(os.getenv('BASE_URL', ''))
    print(json.dumps(result), flush=True)
    if not result['network_reachable']:
        print('Backend not started: provider network access is unavailable. Use a normal terminal; no model request was sent.', file=sys.stderr)
        return 2
    if args.check_only:
        return 0
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run('backend.app:app', host='127.0.0.1', port=args.port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
