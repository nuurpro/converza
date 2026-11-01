"""Free qualification/Atom/budget safety lane; no provider or database access."""
import json

from services.memory import is_complete_claim_quote, rank_sources


CASES = (
    ('entry_en', 'Festival entry is free.', '\nOnly if registration is approved.'),
    ('grant_en', 'Festival grants are available.', '\n- Unless the committee rejects the application.'),
    ('funding_en', 'Festival funding is available.', '\n**Only if** eligibility is confirmed.'),
    ('entry_uz', 'Festival kirish bepul.', '\n- Faqat ro\u2018yxatdan o\u2018tganlar uchun.'),
    ('grant_uz', 'Festival grant ajratadi.', '\n> Agar ariza komissiya tomonidan tasdiqlansa.'),
    ('entry_ru', 'Festival \u0432\u0445\u043e\u0434 \u0431\u0435\u0441\u043f\u043b\u0430\u0442\u043d\u044b\u0439.',
     '\n**\u0422\u043e\u043b\u044c\u043a\u043e** \u0435\u0441\u043b\u0438 \u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430.'),
)


def evaluate():
    results = []
    for name, claim, condition in CASES:
        content = claim + condition
        results.append({'id': name + '_qualification', 'passed':
            is_complete_claim_quote(content, content) and not is_complete_claim_quote(content, claim)})
        oversized = claim + condition.rstrip('.') + ' approved' * 90 + '.'
        source = dict(id=name, org_id='eval', kind='manual', title='Festival', content=oversized,
            revision=1, indexed_revision=1, summary=claim,
            atoms=[{'kind': 'fact', 'text': claim, 'span': [0, len(claim)], 'source_revision': 1}])
        rows = rank_sources([source], 'Festival', org_id='eval', budget_chars=650)
        serialized = json.dumps(rows, ensure_ascii=False)
        results.append({'id': name + '_budget', 'passed': len(serialized) <= 650 and all(
            not row['content'] and not row['summary'] and not row['citation_spans']
            and not any(atom.get('text') for atom in row['atoms']) for row in rows)})
    passed = sum(case['passed'] for case in results)
    return {'lane': 'fixture', 'passed': passed, 'total': len(results),
            'score': passed / len(results), 'threshold': 1.0, 'cases': results}


if __name__ == '__main__':
    report = evaluate()
    print(json.dumps(report, ensure_ascii=True))
    raise SystemExit(report['passed'] != report['total'])
