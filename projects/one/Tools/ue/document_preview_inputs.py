"""Explicit, provenance-bound source selection for reversible document previews."""
from pathlib import Path


def preview_source_path(provenance,default_source):
    if 'source_document' not in provenance:return Path(default_source).resolve()
    source=Path(provenance['source_document']).resolve()
    if str(source) not in provenance['input_sha256']:
        raise ValueError('explicit preview source must be included in candidate provenance')
    return source
