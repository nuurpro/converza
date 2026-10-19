"""Tenant-bound deterministic catalog, checkout, provenance and delivery checks."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from string import Formatter
from urllib.parse import quote, urlsplit

from services.memory import tokenize


def validate_checkout_template(template):
    if template is None or template == '':
        return None
    try:
        parsed = urlsplit(template)
        fields = list(Formatter().parse(template))
        invalid_fields = any(name is not None and (name not in {'sku','quantity'} or spec or conversion)
                             for _, name, spec, conversion in fields)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or invalid_fields:
            raise ValueError()
        if any(c in template for c in '\r\n\t') or '{' in parsed.netloc or '}' in parsed.netloc:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ValueError('Checkout template must be HTTPS with only {sku} and {quantity} placeholders') from exc
    return template


def snapshot_product(product):
    return {'id':str(product['id']), 'sku':product.get('sku'), 'name':product['name'],
            'description':product.get('description') or '',
            'price':str(product['price']) if product.get('price') is not None else None,
            'currency':product.get('currency',''), 'stock_count':product.get('stock_count'),
            'revision':int(product.get('revision',1)), 'checkout_url_template':product.get('checkout_url_template')}


class SalesTools:
    def __init__(self, org_id, products, knowledge):
        self.org_id = str(org_id)
        self.products = [deepcopy(p) for p in products if str(p.get('org_id',org_id)) == self.org_id and not p.get('deleted_at')]
        self.knowledge = [deepcopy(k) for k in knowledge if str(k.get('org_id',org_id)) == self.org_id and not k.get('deleted_at')]

    def query_product_catalog(self, query):
        query = str(query).strip().casefold()
        if not query:
            return []
        exact = [p for p in self.products if (p.get('sku') and p['sku'].casefold() == query) or str(p.get('name','')).casefold() == query]
        if exact:
            return exact
        words = set(tokenize(query))
        return [p for p in self.products if words and words.issubset(set(tokenize(' '.join(str(p.get(k) or '') for k in ('sku','name')))))]

    def lookup_objection_playbook(self, objection_type):
        words=set(tokenize(objection_type))
        return [row for row in self.knowledge if row.get('kind') == 'objection'
                and ((row.get('metadata') or {}).get('status') == 'PUBLISHED')
                and (row.get('metadata') or {}).get('resolved_at') and (row.get('metadata') or {}).get('delivered_at')
                and words.intersection(tokenize(str(row.get('content','')) + ' ' + str(row.get('atoms',[]))))]

    def generate_payment_link(self, sku, quantity):
        if not isinstance(sku,str) or not sku.strip():
            raise ValueError('A verified nonempty SKU is required for checkout')
        if type(quantity) is not int or quantity < 1:
            raise ValueError('Quantity must be a positive integer')
        matches=[p for p in self.products if p.get('sku') == sku]
        if len(matches) != 1:
            raise ValueError('One verified SKU is required for checkout')
        product=matches[0]
        stock=product.get('stock_count')
        if type(stock) is not int or stock < quantity:
            raise ValueError('Known sufficient stock is required for checkout')
        try:
            price=Decimal(str(product.get('price')))
            if not price.is_finite() or price < 0 or not re.fullmatch('[A-Z]{3}',product.get('currency','')):
                raise ValueError()
        except (InvalidOperation, ValueError) as exc:
            raise ValueError('Verified price and currency are required for checkout') from exc
        template=validate_checkout_template(product.get('checkout_url_template'))
        if not template:
            raise ValueError('Merchant checkout is not configured')
        return template.format(sku=quote(sku,safe=''), quantity=str(quantity))


def validate_commerce_snapshot(artifact, products):
    if not artifact:
        return
    current={str(p['id']):snapshot_product(p) for p in products if not p.get('deleted_at')}
    for saved in artifact.get('product_snapshot',[]):
        row=current.get(str(saved['id']))
        if not row or any(row.get(key) != saved.get(key) for key in row):
            raise ValueError('Catalog changed. Refresh the draft and approve its current facts before delivery.')
    if artifact.get('checkout_link'):
        saved=artifact.get('product_snapshot') or []
        if len(saved) != 1 or SalesTools('',[dict(saved[0],org_id='')],[]).generate_payment_link(saved[0]['sku'],artifact['quantity']) != artifact['checkout_link']:
            raise ValueError('Checkout link no longer matches the verified catalog')


def validate_citations(citations, evidence):
    sources={row['source_id']:row for row in evidence}
    for ref in citations:
        source=sources.get(ref['source_id'])
        if not source or source.get('revision') != ref['revision']:
            raise ValueError('Citation source or revision was not supplied')
        index=ref.get('atom_index')
        span=ref.get('span')
        if index is None and span is None:
            raise ValueError('Citation requires an Atom or source span')
        if index is not None and (type(index) is not int or not 0 <= index < len(source.get('atoms') or [])):
            raise ValueError('Citation Atom was not supplied')
        if span is not None and (len(span)!=2 or any(type(n) is not int for n in span) or not 0<=span[0]<span[1]<=len(source.get('content',''))):
            raise ValueError('Citation span was not supplied')
        if span is not None:
            text=source['content'][span[0]:span[1]].strip()
        else:
            atom=source['atoms'][index]
            text=(atom.get('text') or atom.get('answer') or '').strip()
        # A true substring can still reverse a claim by dropping its negation.
        complete_claims={match.group().strip() for match in re.finditer(r'[^.!?\n]+[.!?]?',source.get('content',''))}
        if not text or text not in complete_claims:
            raise ValueError('Citation must preserve a complete source sentence or line')
    return citations


def citation_text(ref, evidence):
    source=next(row for row in evidence if row['source_id']==ref['source_id'])
    if ref.get('span') is not None:
        start,end=ref['span']
        return source['content'][start:end]
    atom=source['atoms'][ref['atom_index']]
    return atom.get('text') or atom.get('answer') or ''
