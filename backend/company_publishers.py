"""Publisher identity rules, never company facts or market-share constants.

Verified against the publishers' public release pages on 2026-10-20. The rule
authenticates attribution and route; it does not certify a dataset's accuracy.
"""
import re
from urllib.parse import urlsplit


RULES = (
    ('sneresearch.com', r'^/(?:en|kr)/insight/release_view/', 'SNE Research',
     r'Source\s*:\s*[^\n]{0,180}(?:Tracker[^\n]{0,80}SNE\s+Research|SNE\s+Research)',
     'https://sneresearch.com/en/insight/release_view/744/page/0'),
    ('idc.com', r'^/resource-center/press-releases/', 'IDC',
     r'(?:Source\s*:\s*IDC|according to[^.\n]{0,180}IDC[^.\n]{0,100}Tracker)',
     'https://www.idc.com/about/press-room/'),
)


def statistics_release_candidate(url):
    try:
        p=urlsplit(str(url or ''))
        host=(p.hostname or '').lower().removeprefix('www.')
        return p.scheme=='https' and not p.username and any(host==h and re.search(path,p.path) for h,path,*_ in RULES)
    except ValueError:return False


def statistics_publisher_identity(url, text):
    if not statistics_release_candidate(url):return {}
    p=urlsplit(url);host=(p.hostname or '').lower().removeprefix('www.')
    for domain,path,name,attribution,reference in RULES:
        if host==domain and re.search(path,p.path) and re.search(attribution,str(text or ''),re.I):
            return {'publisher_role':'statistics_origin','publisher_verified':True,'publisher_name':name,
                'publisher_verification':{'method':'official_release_route_and_original_dataset_attribution',
                    'verified_domain':domain,'reference':reference}}
    return {}
