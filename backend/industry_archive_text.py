"""Repair invalid extracted Unicode before industry archive persistence.

Original URLs/files remain the review basis. Replacement glyphs never authorize
facts, and valid strings (including literal backslash escapes) stay unchanged.
"""
import re

VERSION = 'industry-archive-text-v1-surrogate-guard'
SURROGATES = re.compile(r'[\ud800-\udfff]')
PAIRS = re.compile(r'[\ud800-\udbff][\udc00-\udfff]')


def prepare_archive_text(title, summary, body, metadata):
    counts={'paired_surrogates':0,'unpaired_surrogates':0,'changed_text_fields':0}
    def text(value):
        hits=SURROGATES.findall(value)
        if not hits:return value
        pairs=len(PAIRS.findall(value))
        counts['paired_surrogates']+=pairs
        counts['unpaired_surrogates']+=len(hits)-2*pairs
        counts['changed_text_fields']+=1
        return value.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace')
    def walk(value):
        if isinstance(value,str):return text(value)
        if isinstance(value,list):return [walk(v) for v in value]
        if isinstance(value,tuple):return tuple(walk(v) for v in value)
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                fixed=text(key) if isinstance(key,str) else key
                if fixed in result:raise ValueError('archive_metadata_unicode_key_collision')
                result[fixed]=walk(item)
            return result
        return value
    title,summary,clean_body,meta=walk([title,summary,body,metadata])
    if counts['changed_text_fields']:
        prior=dict(meta.get('text_encoding_review') or {})
        meta['text_encoding_review']={**prior,'version':VERSION,'requires_source_review':True,
            'replacement_marker':'U+FFFD','count_scope':'all_text_fields_in_this_normalization',
            'original_body_characters':len(body),'normalized_body_characters':len(clean_body),
            'character_offsets_changed':len(clean_body)!=len(body),**counts}
    return title,summary,clean_body,meta,counts
