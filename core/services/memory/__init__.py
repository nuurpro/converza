"""Organization-scoped identity exports and rebuildable BM25L retrieval."""
from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from rank_bm25 import BM25L

IDENTITY_FIELDS = ('brand_name', 'industry', 'core_offer', 'target_audience', 'target_location', 'primary_goal', 'hex_colors')
EXPORT_NAMES = ('brand_passport.md', 'voice_rules.md', 'negative_constraints.md')


def _plain(value: Any) -> str:
    if isinstance(value, list):
        return '\n'.join('- ' + str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or '')


def render_identity(passport: dict[str, Any]) -> dict[str, str]:
    """Catalog facts never enter the always-included identity instructions."""
    brand = '# Brand passport\n\n' + '\n'.join(
        f"{key.replace('_', ' ').capitalize()}: {_plain(passport[key])}"
        for key in IDENTITY_FIELDS if passport.get(key)
    ) + '\n'
    voice = '# Voice rules\n\n' + '\n'.join(filter(None, [_plain(passport.get('tone') or passport.get('brand_voice')), _plain(passport.get('voice_rules'))])) + '\n'
    negative = '# Negative constraints\n\n' + _plain(passport.get('negative_constraints') or passport.get('avoid_topics')) + '\n'
    documents = dict(zip(EXPORT_NAMES, (brand, voice, negative)))
    for name, maximum in zip(EXPORT_NAMES, (6000, 3000, 3000)):
        if len(documents[name]) > maximum:
            raise ValueError(f'{name} exceeds {maximum} characters; shorten canonical identity rules before generation')
    return documents


def tokenize(text: str) -> list[str]:
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold(), re.UNICODE)


def legacy_pricing(passport: dict) -> list[dict]:
    pricing = passport.get('pricing')
    if not isinstance(pricing, list):
        return []
    return [{'id': f"passport:{passport.get('id')}:{i}", 'name': str(item.get('tier') or item.get('name') or 'Legacy offer'),
             'price': item.get('price'), 'currency': item.get('currency', ''), 'features': item.get('features', []),
             'origin': 'passport_pricing'} for i, item in enumerate(pricing) if isinstance(item, dict)]


def _legacy_price_terms(pricing: list[dict]) -> list[dict]:
    return [{'price': match, 'currency': 'LEGACY'} for item in pricing
            for match in re.findall(r'[0-9]+(?:\.[0-9]+)?', str(item.get('price') or '').replace(',', ''))]


def _timestamp(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def rank_sources(rows: list[dict], query: str, *, org_id: str, limit: int = 8,
                 budget_chars: int = 12000, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    candidates = []
    corpus = []
    for row in rows:
        if str(row.get('org_id')) != str(org_id) or row.get('deleted_at') or row.get('kind') == 'passport':
            continue
        item = copy.deepcopy(row)
        if item.get('indexed_revision') != item.get('revision'):
            item['summary'], item['atoms'] = '', []
        # The raw catalog record is the only source of product pricing.
        if item.get('kind') == 'product':
            item['summary'], item['atoms'] = '', []
        searchable = '\n'.join([str(item.get('title') or ''), str(item.get('content') or ''), str(item.get('summary') or ''), json.dumps(item.get('atoms') or [], ensure_ascii=False)])
        tokens = tokenize(searchable)
        if tokens:
            candidates.append(item)
            corpus.append(tokens)
    query_tokens = tokenize(query)
    if not corpus or not query_tokens:
        return []
    scores = BM25L(corpus).get_scores(query_tokens)
    ranked = []
    for item, tokens, score in zip(candidates, corpus, scores):
        # BM25L includes a positive non-match baseline. Only lexical matches qualify.
        if not set(query_tokens).intersection(tokens):
            continue
        age = max(0.0, (now - _timestamp(item.get('updated_at'), now)).total_seconds() / 86400)
        adjusted = float(score) * (0.25 + 0.75 * 2 ** (-age / 30))
        ranked.append((adjusted, item))
    ranked.sort(key=lambda x: (-x[0], str(x[1].get('id'))))
    result = []
    remaining = max(0, min(int(budget_chars), 100000))
    for score, item in ranked[:max(0, min(int(limit), 8))]:
        if remaining < 4:
            break
        content = str(item.get('content') or '')[:remaining-2]
        remaining -= len(content)
        summary = str(item.get('summary') or '')[:max(0, remaining-2)]
        remaining -= len(summary)
        atoms = item.get('atoms') or []
        if len(str(atoms)) > remaining:
            atoms = []
        remaining -= len(str(atoms))
        result.append({'source_id': item['id'], 'kind': item['kind'], 'title': item.get('title', ''),
                       'content': content, 'summary': summary, 'atoms': atoms,
                       'revision': item['revision'], 'updated_at': item.get('updated_at'), 'score': score})
    return result


def redact_stale_prices(text: str, history: list[dict], products: list[dict]) -> str:
    current = {(Decimal(str(p['price'])), str(p.get('currency', '')).upper()) for p in products if p.get('price') is not None}
    for price in history:
        value = Decimal(str(price['price']))
        currency = str(price.get('currency', '')).upper()
        if (value, currency) in current:
            continue
        number = re.escape(format(value.normalize(), 'f')) + r'(?:\.0+)?'
        symbol = {'USD': r'\$', 'EUR': '€', 'GBP': '£'}.get(currency)
        # Also redact bare numbers from old quotations. Current catalog stays separate.
        pattern = r'(?<![\d.])(?:' + (('(?:' + symbol + r'\s*)?') if symbol else '') + number + r'(?:\s*' + re.escape(currency) + r')?)(?![\d.])'
        text = re.sub(pattern, '[superseded price]', text, flags=re.IGNORECASE)
    return text


class MemoryStore:
    """Supabase authoritative store. No process-local search cache can outlive a revision."""
    def __init__(self, client: Any):
        self.client = client

    def _rows(self, table: str, org_id: str) -> list[dict]:
        rows = []
        offset = 0
        while True:
            page = self.client.table(table).select('*').eq('org_id', org_id).order('id').range(offset, offset+999).execute().data or []
            rows.extend(page)
            if len(page) < 1000:
                return rows
            offset += 1000

    def _passport(self, org_id: str) -> dict:
        rows = self.client.table('brand_passports').select('*').eq('org_id', org_id).order('updated_at', desc=True).limit(1).execute().data or []
        return rows[0] if rows else {}

    def identity(self, org_id: str) -> dict:
        passport = self._passport(org_id)
        sources = self.client.table('memory_sources').select('revision').eq('org_id', org_id).eq('kind', 'passport').eq('external_id', str(passport.get('id', ''))).limit(1).execute().data or []
        return {'org_id': org_id, 'revision': sources[0]['revision'] if sources else 0,
                'passport': passport, 'exports': render_identity(passport)}

    def save_identity(self, org_id: str, payload: dict) -> dict:
        payload = dict(payload)
        if 'brand_voice' in payload and 'tone' not in payload:
            payload['tone'] = payload['brand_voice']
        if 'avoid_topics' in payload and 'negative_constraints' not in payload:
            payload['negative_constraints'] = payload['avoid_topics']
        allowed = {*IDENTITY_FIELDS, 'tone', 'voice_rules', 'negative_constraints', 'hex_colors', 'onboarding_answers'}
        values = {k: v for k, v in payload.items() if k in allowed}
        existing = self._passport(org_id)
        if not existing:
            raise ValueError('Complete onboarding before editing identity')
        render_identity({**existing, **values})
        self.client.table('brand_passports').update(values).eq('org_id', org_id).eq('id', existing['id']).execute()
        return self.identity(org_id)

    def products(self, org_id: str) -> list[dict]:
        return [r for r in self._rows('brand_products', org_id) if not r.get('deleted_at')]

    def _create(self, table: str, org_id: str, payload: dict, allowed: set) -> dict:
        values = {k: v for k, v in payload.items() if k in allowed}
        if table == 'brand_products':
            self._validate_product(values)
        elif not str(values.get('content') or '').strip():
            raise ValueError('Knowledge content is required')
        if table == 'brand_knowledge' and values.get('kind', 'manual') not in ('faq', 'manual'):
            raise ValueError('Knowledge kind must be faq or manual')
        values['org_id'] = org_id
        return self.client.table(table).insert(values).execute().data[0]

    @staticmethod
    def _validate_product(values: dict) -> None:
        if 'price' in values and values['price'] is not None:
            try:
                price = Decimal(str(values['price']))
            except InvalidOperation as exc:
                raise ValueError('Price must be a nonnegative finite number') from exc
            if not price.is_finite() or price < 0:
                raise ValueError('Price must be a nonnegative finite number')
        if 'currency' in values and not re.fullmatch('[A-Z]{3}', str(values['currency'])):
            raise ValueError('Currency must be a three-letter uppercase code')
        if 'name' in values and not str(values['name']).strip():
            raise ValueError('Product name is required')

    def _update(self, table: str, org_id: str, row_id: str, payload: dict, allowed: set) -> dict:
        values = {k: v for k, v in payload.items() if k in allowed}
        if table == 'brand_products':
            self._validate_product(values)
        if table == 'brand_knowledge':
            if 'kind' in values and values['kind'] not in ('faq', 'manual'):
                raise ValueError('Knowledge kind must be faq or manual')
            if 'content' in values and not str(values['content'] or '').strip():
                raise ValueError('Knowledge content is required')
        rows = self.client.table(table).update(values).eq('org_id', org_id).eq('id', row_id).is_('deleted_at', 'null').execute().data or []
        if not rows:
            raise KeyError(row_id)
        return rows[0]

    def create_product(self, org_id: str, payload: dict) -> dict:
        if not str(payload.get('name') or '').strip():
            raise ValueError('Product name is required')
        return self._create('brand_products', org_id, payload, {'name', 'description', 'price', 'currency', 'metadata'})

    def update_product(self, org_id: str, product_id: str, payload: dict) -> dict:
        return self._update('brand_products', org_id, product_id, payload, {'name', 'description', 'price', 'currency', 'metadata'})

    def delete_product(self, org_id: str, product_id: str) -> bool:
        return bool(self.client.rpc('memory_forget', {'p_org': org_id, 'p_kind': 'product', 'p_id': product_id}).execute().data)

    def knowledge(self, org_id: str) -> list[dict]:
        rows = [r for r in self._rows('brand_knowledge', org_id) if not r.get('deleted_at')]
        sources = {(r['kind'], r['external_id']): r for r in self._rows('memory_sources', org_id)}
        for row in rows:
            source = sources.get((row['kind'], str(row['id'])), {})
            row['source_id'] = source.get('id')
            row['indexing_status'] = source.get('indexing_status', 'pending')
            row['indexed_revision'] = source.get('indexed_revision')
            row['summary'] = source.get('summary', '') if source.get('indexed_revision') == source.get('revision') else ''
            row['atoms'] = source.get('atoms', []) if source.get('indexed_revision') == source.get('revision') else []
        for source in sources.values():
            if (source['kind'] == 'objection' or source.get('metadata', {}).get('origin') == 'passport') and not source.get('deleted_at'):
                rows.append({**source, 'source_id': source['id'], 'read_only': True})
        return rows

    def create_knowledge(self, org_id: str, payload: dict) -> dict:
        return self._create('brand_knowledge', org_id, payload, {'kind', 'title', 'content'})

    def update_knowledge(self, org_id: str, knowledge_id: str, payload: dict) -> dict:
        return self._update('brand_knowledge', org_id, knowledge_id, payload, {'kind', 'title', 'content'})

    def delete_knowledge(self, org_id: str, knowledge_id: str) -> bool:
        return bool(self.client.rpc('memory_forget', {'p_org': org_id, 'p_kind': 'knowledge', 'p_id': knowledge_id}).execute().data)

    def forget_source(self, org_id: str, source_id: str) -> bool:
        return bool(self.client.rpc('memory_forget_source', {'p_org': org_id, 'p_source': source_id}).execute().data)

    def search(self, org_id: str, query: str, limit: int = 8, budget_chars: int = 12000) -> list[dict]:
        rows = self._rows('memory_sources', org_id)
        products = self.products(org_id)
        catalog = {str(product['id']): product for product in products}
        legacy_sources = any(row.get('metadata', {}).get('origin') == 'passport' for row in rows)
        passport = self.identity(org_id)['passport'] if legacy_sources else {}
        legacy = legacy_pricing(passport)
        current_price_terms = products + _legacy_price_terms(legacy)
        history = self._rows('memory_price_history', org_id)
        # Redact copies for retrieval while keeping exact stored source quotes inspectable.
        for row in rows:
            metadata = row.get('metadata') or {}
            if metadata.get('origin') == 'passport':
                field = metadata['source_field']
                value = passport.get(field)
                if str(metadata.get('passport_id')) != str(passport.get('id')) or not value:
                    row['deleted_at'] = True
                    continue
                try:
                    previous_value = json.loads(str(row.get('content', '')).split('\n', 1)[1])
                except (ValueError, IndexError):
                    previous_value = None
                # Current raw legacy prices/FAQs override pending or obsolete extraction.
                row['content'] = field + '\n' + json.dumps(value, ensure_ascii=False, sort_keys=True)
                if field == 'pricing' or previous_value != value:
                    row['summary'], row['atoms'], row['indexed_revision'] = '', [], None
            if row['kind'] == 'product':
                product = catalog.get(str(row.get('external_id')))
                if product is None:
                    row['deleted_at'] = True
                    continue
                row['title'] = product['name']
                row['content'] = f"{product['name']}\n{product.get('description') or ''}\nCurrent price: {product.get('price', 'not specified')} {product.get('currency', '')}"
            else:
                for key in ('content', 'summary'):
                    row[key] = redact_stale_prices(str(row.get(key) or ''), history, current_price_terms)
                for atom in row.get('atoms') or []:
                    for key in ('text', 'objection', 'answer'):
                        if isinstance(atom.get(key), str):
                            quoted = atom[key]
                            atom[key] = redact_stale_prices(quoted, history, current_price_terms)
                            if quoted != atom[key]:
                                atom['quote_redacted'] = True
        return rank_sources(rows, query, org_id=org_id, limit=limit, budget_chars=budget_chars)

    def context(self, org_id: str, query: str) -> dict:
        identity = self.identity(org_id)
        knowledge = self.search(org_id, query)
        catalog = self.products(org_id) + legacy_pricing(identity['passport'])
        if len(catalog) > 8:
            product_query = query + '\n' + '\n'.join(row['title'] for row in knowledge if row['kind'] == 'product')
            candidates = [{'id':str(product['id']),'org_id':org_id,'kind':'product','title':product['name'],
                           'content':f"{product['name']} {product.get('price', '')} {product.get('currency', '')}",
                           'revision':1,'updated_at':product.get('updated_at')} for product in catalog]
            matched = {row['source_id'] for row in rank_sources(candidates, product_query, org_id=org_id, budget_chars=6000)}
            catalog = [product for product in catalog if str(product['id']) in matched]
        prices = []
        budget = 6000
        for product in catalog:
            price = {key:product.get(key) for key in ('id','name','price','currency')}
            size = len(json.dumps(price, ensure_ascii=False, default=str))
            if size <= budget:
                prices.append(price)
                budget -= size
        return {'identity': identity, 'knowledge': knowledge, 'products': prices}

    def jobs(self, org_id: str) -> list[dict]:
        return self.client.table('memory_index_jobs').select('*').eq('org_id', org_id).order('created_at', desc=True).limit(100).execute().data or []

    def retry_job(self, org_id: str, job_id: str) -> dict:
        rows = self.client.rpc('memory_retry_job', {'p_org': org_id, 'p_job': job_id}).execute().data or []
        if not rows:
            raise KeyError(job_id)
        return rows[0] if isinstance(rows, list) else rows
