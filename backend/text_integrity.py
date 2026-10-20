"""Conservative decoding and damage detection; never guess missing characters."""
import re


def text_issues(text):
    text = str(text or '')
    issues = []
    if '\ufffd' in text:
        issues.append('replacement_character')
    if re.search(r'锟斤拷|烫{3,}|屯{3,}|浜哄伐|鏅鸿兘|鏈哄櫒|鍥剧墖|鍏冩暟鎹', text):
        issues.append('mojibake')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]', text):
        issues.append('invalid_text_character')
    # Successful strict reversal is a strong sign of UTF-8 decoded as a
    # Western single-byte encoding. Real French/Swedish names fail this test.
    for match in re.finditer(r'[A-Za-z\u0080-\u024f\u2000-\u206f\u20ac\u2122]{2,}', text):
        token = match[0]
        if not re.search(r'[ÃÂâäåæçèé]', token):
            continue
        for encoding in ('latin1', 'cp1252'):
            try:
                restored = token.encode(encoding).decode('utf-8')
            except (UnicodeError, LookupError):
                continue
            if restored != token and (re.search(r'[\u4e00-\u9fff]', restored)
                                      or sum(ord(c) > 127 for c in restored) < sum(ord(c) > 127 for c in token)):
                issues.append('mojibake')
                break
        if 'mojibake' in issues:
            break
    if (len(re.findall(r'[ÃÂåæçäèé]', text)) >= 3
            and len(re.findall(r'[\x80-\xbf\u0152\u0153\u2010-\u203f]', text)) >= 3):
        issues.append('mojibake')
    return list(dict.fromkeys(issues))


def decode_http_text(response):
    """Prefer lossless UTF-8 bytes over requests' implicit ISO-8859-1 default."""
    payload = getattr(response, 'content', None)
    if not isinstance(payload, bytes):
        return str(getattr(response, 'text', '') or '')
    if payload.startswith((b'\xff\xfe', b'\xfe\xff')):
        return payload.decode('utf-16')
    meta = re.search(br'charset\s*=\s*["\']?([A-Za-z0-9._-]+)', payload[:8192], re.I)
    declared = meta[1].decode('ascii') if meta else ''
    header = str((getattr(response, 'headers', {}) or {}).get('Content-Type', ''))
    charset = re.search(r'charset\s*=\s*["\']?([A-Za-z0-9._-]+)', header, re.I)
    encodings = [declared, charset[1] if charset else '', 'utf-8-sig',
                 getattr(response, 'apparent_encoding', ''), getattr(response, 'encoding', '')]
    for encoding in dict.fromkeys(e for e in encodings if e):
        try:
            return payload.decode(encoding, errors='strict')
        except (UnicodeError, LookupError):
            continue
    # Replacement is explicit damage, not a successful repair; admission and
    # delivery checks will hold affected passages while preserving raw input.
    return payload.decode('utf-8', errors='replace')
