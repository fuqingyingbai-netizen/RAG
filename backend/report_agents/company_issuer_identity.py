"""Issuer-declared sites and bilingual legal names, with original proof.

This authenticates self-disclosure ownership only. It is not a registry match,
proof of a subsidiary relationship, or a control/transaction conclusion.
"""
import re
from urllib.parse import urlparse

from .company_text import OriginalTextView,issuer_anchor,match_compact,match_text

CORPORATE_SUBDOMAINS={'home','ir','investor','investors','static','reports'}
EXCHANGES=('hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn')
URL=r'(?:https?://)?(?:www\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}(?:/[^\s|<>）)」”]*)?'


def website_declarations(raw):
    view=OriginalTextView(str(raw or '')[:6500]);rows=[]
    patterns=[r'(?:网站|网址|Website)\s*[:：]\s*(?P<url>'+URL+r')',
              r'(?:本公司|本集团|公司(?:的)?|our(?:\s+corporate)?|the\s+company[’\']s)\s*(?:网站|网址|website)\s*[:：]?\s*(?P<url>'+URL+r')']
    for pattern in patterns:
        for m in re.finditer(pattern,view.text,re.I):
            value=view.quote(m.start('url'),m.end('url'))
            host=(urlparse(value if re.match(r'https?://',value) else 'https://'+value).hostname or '').lower().removeprefix('www.')
            if not host or host in {'hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn'}:continue
            rows.append({'host':host,'url':value,'evidence_quote':view.quote(m.start(),m.end())})
    return list({(r['host'],r['evidence_quote']):r for r in rows}.values())


def bilingual_cover_names(raw,target):
    if not issuer_anchor(raw,target)['matched']:return []
    lines=[line.strip() for line in str(raw or '')[:6500].splitlines() if line.strip()]
    rows=[]
    for i,line in enumerate(lines):
        if match_compact(line)!=match_compact(target) or not i:continue
        previous=lines[i-1]
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9 &.,’\'-]{2,100}\b(?:Limited|Ltd\.?|Inc\.?|Corporation)',previous,re.I):continue
        rows.append({'name':previous,'target_name':target,'evidence_quote':previous+'\n'+line})
    return list({r['name'].casefold():r for r in rows}.values())


def build_issuer_identity(sources,target):
    from .company_governance import get,_primary_filing
    from .company_evidence import source_body
    roots=set();sites=[];aliases=[]
    for s in sources or []:
        meta=get(s,'source_metadata',{}) or {}
        if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:continue
        if not _primary_filing(s,target):continue
        raw,origin=source_body(s)
        if origin=='discovery_summary':continue
        for row in website_declarations(raw):
            sites.append({**row,'source_url':str(get(s,'url'))});roots.add(row['host'])
        for row in bilingual_cover_names(raw,target):aliases.append({**row,'source_url':str(get(s,'url'))})
    return {'target_name':target,'roots':roots,'websites':sites,'bilingual_names':aliases}


def publisher_anchor(source,target,identity):
    from .company_governance import get
    from .company_evidence import source_body
    meta=get(source,'source_metadata',{}) or {}
    if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:return {}
    raw,origin=source_body(source)
    if origin=='discovery_summary':return {}
    parsed=urlparse(str(get(source,'url') or ''));host=(parsed.hostname or '').lower().removeprefix('www.')
    if parsed.scheme not in {'http','https'} or parsed.username:return {}
    roots=identity.get('roots') or set()
    root=next((r for r in roots if host==r or (host.endswith('.'+r) and host[:-len(r)-1] in CORPORATE_SUBDOMAINS)),None)
    exchange=any(host==r or host.endswith('.'+r) for r in EXCHANGES)
    if not root and not exchange:return {}
    direct=issuer_anchor(raw,target)
    if direct.get('conflicting_heading'):return {}
    if direct['matched']:return direct
    if not root:return {}  # a footer cannot own another exchange issuer's filing
    name=r'\s*'.join(map(re.escape,match_text(target)))
    # HTML extractors can append large data-URI icons after the footer. Match
    # bounded literal copyright passages, not just the final character budget.
    for marker in re.finditer(r'©|Copyright|版[权權]公告',raw,re.I):
        view=OriginalTextView(raw[marker.start():marker.start()+400])
        copyright=re.search(r'(?:©|版权公告|Copyright)[^\n]{0,100}(?P<issuer>'+name+r')',view.text,re.I)
        if copyright:
            return {'matched':True,'issuer_name':view.quote(copyright.start('issuer'),copyright.end('issuer')),
                'evidence_quote':view.quote(copyright.start(),copyright.end()),'publisher_statement':True,'publisher_only':True}
    # An English press statement needs an exact legal name independently
    # paired with this target on an authenticated bilingual filing cover.
    return _bilingual_anchor(raw,target,identity,root,host)


def _bilingual_anchor(raw,target,identity,root,host):
    for alias in identity.get('bilingual_names') or []:
        view=OriginalTextView(raw[:8000]);name=re.escape(alias['name'])
        m=re.search(r'(?P<issuer>'+name+r')\s*\([^\n]{5,260}\)\s*(?:today\s+)?announced\b',view.text,re.I)
        if not m:continue
        site=next((s for s in identity.get('websites',[]) if s['host']==root),None)
        if not site:continue
        return {'matched':True,'issuer_name':target,'evidence_quote':view.quote(m.start(),m.end()),
            'bilingual_binding':{'target_name':target,'original_legal_name':alias['name'],
                'cover_quote':alias['evidence_quote'],'cover_source_url':alias['source_url'],
                'website_quote':site['evidence_quote'],'website_source_url':site['source_url'],
                'declared_host':root,'publisher_host':host},'publisher_statement':True}
    return {}


def bilingual_publisher_anchor(source,target,identity):
    from .company_governance import get
    from .company_evidence import source_body
    anchor=publisher_anchor(source,target,identity)
    if not anchor:return {}
    if anchor.get('bilingual_binding'):return anchor
    host=(urlparse(str(get(source,'url') or '')).hostname or '').lower().removeprefix('www.')
    root=next((r for r in identity.get('roots',set()) if host==r or
               (host.endswith('.'+r) and host[:-len(r)-1] in CORPORATE_SUBDOMAINS)),None)
    if not root:return {}
    # A Chinese copyright footer authenticates the publisher, while the
    # bilingual cover supplies the exact English legal-action subject.
    return _bilingual_anchor(source_body(source)[0],target,identity,root,host)


def issuer_hosts(sources,target,identity=None):
    from .company_governance import get
    identity=identity or build_issuer_identity(sources,target)
    hosts=set(identity['roots'])
    for s in sources or []:
        host=(urlparse(str(get(s,'url') or '')).hostname or '').lower().removeprefix('www.')
        if any(host.endswith('.'+r) and host[:-len(r)-1] in CORPORATE_SUBDOMAINS for r in identity['roots']):
            if publisher_anchor(s,target,identity):hosts.add(host)
    return hosts


def binding_matches_fact(fact,target):
    binding=fact.get('source_issuer_binding') or {}
    if match_compact(binding.get('target_name'))!=match_compact(target):return False
    legal=str(binding.get('original_legal_name') or '')
    cover=str(binding.get('cover_quote') or '')
    quote=str(fact.get('source_issuer_quote') or '')
    if not legal or match_compact(legal) not in match_compact(cover) or match_compact(target) not in match_compact(cover):return False
    if match_compact(legal) not in match_compact(quote):return False
    host=(urlparse(str(binding.get('cover_source_url') or '')).hostname or '').lower()
    if not any(host==r or host.endswith('.'+r) for r in EXCHANGES):return False
    root=str(binding.get('declared_host') or '')
    if root not in {r['host'] for r in website_declarations(binding.get('website_quote'))}:return False
    actual=(urlparse(str(fact.get('source_url') or '')).hostname or '').lower().removeprefix('www.')
    return bool(root and actual==binding.get('publisher_host') and
                (actual==root or (actual.endswith('.'+root) and actual[:-len(root)-1] in CORPORATE_SUBDOMAINS)))
