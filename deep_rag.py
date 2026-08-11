from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

_PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

# Canonical ontology. Aliases are normalized and resolved longest-first so a
# specific vehicle never becomes two entities (e.g. "پیکان کفی دار" + "پیکان").
_VEHICLE_ALIASES: dict[str, tuple[str, ...]] = {
    'نیسان': ('نیسان', 'نیسان وانت', 'وانت نیسان'),
    'پیکان کفی دار': ('پیکان کفی دار', 'پیکان کفی‌دار', 'پیکان کفی'),
    'پیکان بدون کفی': ('پیکان بدون کفی', 'پیکان بی کفی', 'پیکان بی‌کفی'),
    'خاور مسقف': ('خاور مسقف', 'خاور سقف دار', 'خاور سقف‌دار'),
    'خاور روباز': ('خاور روباز', 'خاور رو باز', 'خاور بدون سقف'),
    'اریسان': ('اریسان', 'آریسان'),
    'پیکان': ('پیکان', 'پیکان وانت', 'وانت پیکان'),
    'خاور': ('خاور', 'کامیون خاور'),
    'وانت': ('وانت',),
}
_VEHICLES = tuple(_VEHICLE_ALIASES.keys())
_RULE_MARKERS = ('باید', 'مجاز', 'ممنوع', 'لازم', 'امکان', 'قانون', 'قاعده', 'الزام', 'محدودیت')
_CONDITION_MARKERS = ('اگر', 'در صورتی', 'در شرایط', 'به شرط', 'وقتی', 'زمانی که', 'مشروط')
_EXCEPTION_MARKERS = ('استثنا', 'تبصره', 'مگر', 'به جز', 'به‌جز', 'فقط در')
_LIMIT_MARKERS = ('حداقل', 'حداکثر', 'بیشتر از', 'کمتر از', 'تا سقف', 'ظرفیت', 'وزن', 'طول', 'عرض', 'ارتفاع')
_COMPARISON_MARKERS = ('مقایسه', 'بهتر', 'فرق', 'تفاوت', 'کدام', 'کدوم')
_CAUSAL_MARKERS = ('چرا', 'علت', 'دلیل', 'به چه دلیل')
_PROCEDURE_MARKERS = ('چطور', 'چگونه', 'مراحل', 'مرحله', 'روش', 'فرایند')
_DECISION_MARKERS = (
    'می تواند', 'میتواند', 'می تونه', 'میتونه', 'می تونیم', 'میتونیم', 'می شه', 'میشه',
    'بشه', 'مجاز است', 'قبول', 'انجام دهد', 'بزنیم', 'می توان', 'میتوان', 'امکان دارد',
)
_STOPWORDS = {
    'را','رو','به','از','در','با','برای','که','این','اون','آن','یک','یه','و','یا','هم','است','هست','باشد','باشه',
    'می','شود','شده','کن','کرد','بده','بگو','لطفا','لطفاً','آیا','چی','چیه','چه','مورد','بررسی','کنید','کنم','کنیم',
}

_PERSIAN_ONES = {
    'صفر':0,'یک':1,'یه':1,'دو':2,'سه':3,'چهار':4,'پنج':5,'شش':6,'شیش':6,'هفت':7,'هشت':8,'نه':9,
    'ده':10,'یازده':11,'دوازده':12,'سیزده':13,'چهارده':14,'پانزده':15,'شانزده':16,'هفده':17,'هجده':18,'نوزده':19,
}
_PERSIAN_TENS = {'بیست':20,'سی':30,'چهل':40,'پنجاه':50,'شصت':60,'هفتاد':70,'هشتاد':80,'نود':90}
_PERSIAN_HUNDREDS = {'صد':100,'یکصد':100,'دویست':200,'سیصد':300,'چهارصد':400,'پانصد':500,'ششصد':600,'هفتصد':700,'هشتصد':800,'نهصد':900}
_NUMBER_WORDS = tuple(sorted(set(_PERSIAN_ONES)|set(_PERSIAN_TENS)|set(_PERSIAN_HUNDREDS)|{'هزار','نیم','و'}, key=len, reverse=True))
_UNIT_CANONICAL = {
    'کیلوگرم':'کیلوگرم','کیلو':'کیلوگرم','kg':'کیلوگرم','تن':'تن','متر':'متر','متری':'متر',
    'سانتی متر':'سانتی متر','سانتیمتر':'سانتی متر','سانتی':'سانتی متر','ساعت':'ساعت','دقیقه':'دقیقه',
    'درصد':'درصد','٪':'درصد','تومان':'تومان','ریال':'ریال',
}
_UNIT_PATTERN = r'(?:کیلوگرم|کیلو|kg|تن|سانتی\s*متر|سانتیمتر|سانتی|متر(?:ی)?|ساعت|دقیقه|درصد|٪|تومان|ریال)'


def _norm(text: str) -> str:
    text = str(text or '').translate(_PERSIAN_DIGITS).replace('\u200c', ' ')
    text = re.sub(r'[يى]', 'ی', text)
    text = re.sub(r'ك', 'ک', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def _tokens(text: str) -> list[str]:
    # Arabic/Persian punctuation (e.g. ؟) lives inside the broad Unicode Arabic
    # block, so strip punctuation before tokenization instead of matching the
    # whole block directly.
    clean=re.sub(r'[^\w\s.,]', ' ', _norm(text), flags=re.UNICODE)
    return [x for x in re.findall(r'\w+(?:[.,]\d+)?', clean, flags=re.UNICODE) if len(x) > 1 and x not in _STOPWORDS]


def _parse_persian_number_phrase(phrase: str) -> float | None:
    tokens=[t for t in _norm(phrase).split() if t and t!='و']
    if not tokens:
        return None
    total=0.0; group=0.0; seen=False
    for token in tokens:
        if token=='نیم':
            group += 0.5; seen=True
        elif token in _PERSIAN_ONES:
            group += _PERSIAN_ONES[token]; seen=True
        elif token in _PERSIAN_TENS:
            group += _PERSIAN_TENS[token]; seen=True
        elif token in _PERSIAN_HUNDREDS:
            group += _PERSIAN_HUNDREDS[token]; seen=True
        elif token=='هزار':
            total += (group or 1.0)*1000; group=0.0; seen=True
        else:
            return None
    return total+group if seen else None


def _fmt_number(value: float) -> str:
    if abs(value-round(value))<1e-9:
        return str(int(round(value)))
    return (f'{value:.3f}').rstrip('0').rstrip('.')


def _numbers(text: str) -> list[str]:
    n=_norm(text)
    out: list[str]=[]
    # Digits + optional units.
    for m in re.finditer(rf'(?<!\w)(\d+(?:[.,]\d+)?)(?:\s*({_UNIT_PATTERN}))?', n, flags=re.I):
        raw=m.group(1).replace(',','.')
        unit=_UNIT_CANONICAL.get(re.sub(r'\s+',' ',m.group(2) or '').strip(), '')
        value=f'{raw} {unit}'.strip()
        if value not in out: out.append(value)
    # Persian written numbers next to a domain unit: "سه متری", "دو و نیم متر".
    words='|'.join(map(re.escape,_NUMBER_WORDS))
    for m in re.finditer(rf'((?:(?:{words})\s*){{1,8}})\s*({_UNIT_PATTERN})', n, flags=re.I):
        value=_parse_persian_number_phrase(m.group(1))
        if value is None: continue
        unit_raw=re.sub(r'\s+',' ',m.group(2)).strip()
        unit=_UNIT_CANONICAL.get(unit_raw, 'متر' if unit_raw.endswith('متری') else unit_raw)
        rendered=f'{_fmt_number(value)} {unit}'.strip()
        if rendered not in out: out.append(rendered)
    return out


def _entities(text: str) -> list[str]:
    n=_norm(text)
    matches: list[tuple[int,int,str]]= []
    for canonical,aliases in _VEHICLE_ALIASES.items():
        for alias in aliases:
            a=_norm(alias)
            for match in re.finditer(rf'(?<![\w\u0600-\u06ff]){re.escape(a)}(?![\w\u0600-\u06ff])', n):
                matches.append((match.start(),match.end(),canonical))
    # Longest match wins for overlapping spans.
    matches.sort(key=lambda x:(-(x[1]-x[0]),x[0],x[2]))
    occupied: list[tuple[int,int]]=[]; chosen: list[tuple[int,str]]=[]
    for start,end,canonical in matches:
        if any(not (end<=a or start>=b) for a,b in occupied):
            continue
        occupied.append((start,end));chosen.append((start,canonical))
    chosen.sort(key=lambda x:x[0])
    return list(dict.fromkeys(c for _,c in chosen))


def _intent(text: str) -> str:
    n = _norm(text)
    if any(_norm(x) in n for x in _COMPARISON_MARKERS): return 'comparison'
    if any(_norm(x) in n for x in _CAUSAL_MARKERS): return 'cause'
    if any(_norm(x) in n for x in _PROCEDURE_MARKERS): return 'procedure'
    if any(_norm(x) in n for x in _DECISION_MARKERS): return 'decision'
    if any(_norm(x) in n for x in _LIMIT_MARKERS): return 'limit'
    return 'fact'


@dataclass(slots=True)
class QueryPlan:
    original: str
    normalized: str
    intent: str
    entities: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    subqueries: list[str] = field(default_factory=list)
    complexity: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            'original': self.original,
            'normalized': self.normalized,
            'intent': self.intent,
            'entities': list(self.entities),
            'numbers': list(self.numbers),
            'concepts': list(self.concepts),
            'flags': list(self.flags),
            'subqueries': list(self.subqueries),
            'complexity': round(float(self.complexity), 4),
        }


def analyze_query(question: str, *, max_subqueries: int = 6) -> QueryPlan:
    original = str(question or '').strip()
    normalized = _norm(original)
    entities = _entities(original)
    numbers = _numbers(original)
    tokens = _tokens(original)
    # Keep retrieval concepts focused on the cargo/topic itself. Vehicle aliases,
    # units, number words and conversational decision verbs are already represented
    # structurally and should not be duplicated into every generated subquery.
    entity_words={part for entity in entities for part in _norm(entity).split()}
    number_words=set(_NUMBER_WORDS)|set(_UNIT_CANONICAL)|{'متری'}
    functional_words={part for marker in (_DECISION_MARKERS+_CONDITION_MARKERS+_EXCEPTION_MARKERS+_LIMIT_MARKERS) for part in _norm(marker).split()}
    ignored=entity_words|number_words|functional_words
    concepts: list[str] = []
    for token in tokens:
        if token not in ignored and not re.fullmatch(r'\d+(?:[.,]\d+)?',token) and token not in concepts:
            concepts.append(token)
    concepts = concepts[:12]

    flags: list[str] = []
    if any(x in normalized for x in _CONDITION_MARKERS): flags.append('conditional')
    if any(x in normalized for x in _EXCEPTION_MARKERS): flags.append('exception_sensitive')
    if any(x in normalized for x in _LIMIT_MARKERS): flags.append('limit_sensitive')
    if numbers: flags.append('numeric')
    if len(entities) > 1: flags.append('multi_entity')
    intent = _intent(original)
    if intent in {'comparison','cause','procedure','decision'}: flags.append('reasoning')

    # Query decomposition remains deterministic and source-first. It does not answer
    # the question; it only broadens retrieval around constraints that are often
    # separated across different pages/chunks.
    subqueries: list[str] = [original]
    entity_phrase = ' '.join(entities[:2]).strip()
    concept_phrase = ' '.join(concepts[:7]).strip()
    base = ' '.join(x for x in (entity_phrase, concept_phrase) if x).strip() or original

    def add(value: str) -> None:
        value = re.sub(r'\s+', ' ', value).strip()
        if value and value not in subqueries and len(subqueries) < max_subqueries:
            subqueries.append(value)

    if numbers:
        add(f"{base} {' '.join(numbers[:4])} محدودیت ظرفیت")
    if entities:
        add(f"{entity_phrase} ظرفیت وزن طول عرض ارتفاع بار")
    if 'conditional' in flags or intent == 'decision':
        add(f"{base} شرط شرایط مجاز ممنوع")
    if 'exception_sensitive' in flags or 'limit_sensitive' in flags or intent in {'decision','limit'}:
        add(f"{base} تبصره استثنا حداقل حداکثر")
    if intent == 'procedure':
        add(f"{base} مراحل روش فرایند")
    if intent == 'comparison':
        add(f"{base} تفاوت مقایسه شرایط")

    complexity = 0.12
    complexity += min(0.28, max(0, len(concepts) - 3) * 0.035)
    complexity += min(0.18, len(numbers) * 0.06)
    complexity += min(0.18, max(0, len(entities) - 1) * 0.09)
    complexity += 0.12 if 'conditional' in flags else 0.0
    complexity += 0.10 if 'exception_sensitive' in flags else 0.0
    complexity += 0.12 if intent in {'comparison','cause','procedure','decision'} else 0.0
    # Interaction matters more than raw token count: a decision involving a numeric
    # constraint or an exception should enter the deeper route even when phrased briefly.
    if intent in {'comparison','cause','procedure','decision'} and ('numeric' in flags or 'exception_sensitive' in flags):
        complexity += 0.08
    complexity = max(0.0, min(1.0, complexity))
    return QueryPlan(original, normalized, intent, entities, numbers, concepts, flags, subqueries, complexity)


def _item_key(item: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(item.get('document_id') or item.get('training_id') or item.get('file_name') or ''),
        int(item.get('chunk_index') or 0),
        str(item.get('source_type') or ''),
    )


def merge_multiretrieval(
    plan: QueryPlan,
    result_sets: Iterable[tuple[str, list[dict[str, Any]]]],
    *,
    top_n: int = 24,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int, str], dict[str, Any]] = {}
    for query_index, (query, rows) in enumerate(result_sets):
        weight = 1.0 if query_index == 0 else max(0.62, 0.90 - query_index * 0.055)
        for rank, raw in enumerate(rows):
            item = dict(raw)
            key = _item_key(item)
            score = float(item.get('score') or item.get('rerank_score') or 0.0)
            contribution = score * weight * (1.0 / (1.0 + rank * 0.035))
            current = merged.get(key)
            if current is None:
                current = item
                current['deep_query_hits'] = 0
                current['deep_query_score'] = 0.0
                current['matched_subqueries'] = []
                merged[key] = current
            current['deep_query_hits'] = int(current.get('deep_query_hits') or 0) + 1
            current['deep_query_score'] = float(current.get('deep_query_score') or 0.0) + contribution
            if query not in current['matched_subqueries']:
                current['matched_subqueries'].append(query)
            current['score'] = max(float(current.get('score') or 0.0), score)

    output: list[dict[str, Any]] = []
    total_queries = max(1, len(plan.subqueries))
    qnums = set(plan.numbers)
    for item in merged.values():
        content = _norm(f"{item.get('file_name','')} {item.get('section_title','')} {item.get('content','')} {item.get('answer','')}")
        coverage = int(item.get('deep_query_hits') or 0) / total_queries
        entity_hits = sum(1 for entity in plan.entities if _norm(entity) in content)
        numeric_hits = sum(1 for number in qnums if _norm(number) in content)
        item['query_coverage_score'] = round(coverage, 5)
        item['entity_alignment_score'] = round(entity_hits / max(1, len(plan.entities)), 5) if plan.entities else 0.0
        item['number_alignment_score'] = round(numeric_hits / max(1, len(qnums)), 5) if qnums else 0.0
        item['deep_query_score'] = round(float(item.get('deep_query_score') or 0.0), 5)
        output.append(item)
    output.sort(key=lambda x: (-float(x.get('deep_query_score') or 0.0), -float(x.get('score') or 0.0)))
    return output[:max(1, top_n)]


def semantic_rerank_candidates(plan: QueryPlan, candidates: list[dict[str, Any]], *, top_n: int = 16) -> list[dict[str, Any]]:
    """Deterministic semantic pre-ranker with intent/entity/number alignment and diversity.

    This fast layer combines signals already produced by the hybrid retriever; R35 can
    optionally follow it with a model-based reranker for complex questions. It deliberately penalizes contradictory intent terms and
    duplicate neighbouring chunks so one long PDF cannot monopolize the context.
    """
    contradiction_pairs = (
        (('مجاز','امکان','قبول'), ('ممنوع','غیرمجاز','رد')),
        (('افزایش','بیشتر'), ('کاهش','کمتر')),
        (('بارگیری',), ('تخلیه',)),
    )
    qn = plan.normalized
    rescored: list[dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        content = _norm(f"{item.get('file_name','')} {item.get('section_title','')} {item.get('content','')} {item.get('answer','')}")
        base = max(float(item.get('score') or 0.0), float(item.get('rerank_score') or 0.0))
        query_coverage = float(item.get('query_coverage_score') or 0.0)
        entity_alignment = float(item.get('entity_alignment_score') or 0.0)
        number_alignment = float(item.get('number_alignment_score') or 0.0)
        token_set = set(_tokens(content))
        concept_alignment = len(set(plan.concepts) & token_set) / max(1, len(set(plan.concepts)))
        rule_bonus = 0.05 if any(x in content for x in _RULE_MARKERS) else 0.0
        exception_bonus = 0.06 if ('exception_sensitive' in plan.flags or 'limit_sensitive' in plan.flags) and any(x in content for x in _EXCEPTION_MARKERS + _LIMIT_MARKERS) else 0.0
        contradiction = 0.0
        qtoken_set=set(_tokens(qn))
        def marker_hit(text_value: str, token_values: set[str], marker: str) -> bool:
            marker_n=_norm(marker)
            return (marker_n in token_values) if ' ' not in marker_n else (marker_n in text_value)
        for left, right in contradiction_pairs:
            if (any(marker_hit(qn,qtoken_set,x) for x in left) and any(marker_hit(content,token_set,x) for x in right)) or (any(marker_hit(qn,qtoken_set,x) for x in right) and any(marker_hit(content,token_set,x) for x in left)):
                contradiction = max(contradiction, 0.22)
        score = (
            base * 0.58 + query_coverage * 0.22 + concept_alignment * 0.10 +
            entity_alignment * 0.07 + number_alignment * 0.08 + rule_bonus + exception_bonus - contradiction
        )
        item['deep_semantic_score'] = round(max(0.0, score), 5)
        item['contradiction_penalty'] = contradiction
        rescored.append(item)
    rescored.sort(key=lambda x: (-float(x.get('deep_semantic_score') or 0.0), -float(x.get('score') or 0.0)))

    # MMR-like diversity: avoid filling the prompt with adjacent chunks from one doc.
    selected: list[dict[str, Any]] = []
    per_doc: dict[str, int] = {}
    seen_chunk_windows: set[tuple[str, int]] = set()
    for item in rescored:
        doc = str(item.get('document_id') or item.get('file_name') or '')
        idx = int(item.get('chunk_index') or 0)
        window = (doc, idx // 2)
        duplicate_window = window in seen_chunk_windows
        doc_count = per_doc.get(doc, 0)
        if selected and duplicate_window and doc_count >= 2:
            continue
        clone = dict(item)
        diversity_penalty = min(0.12, doc_count * 0.025)
        clone['deep_semantic_score'] = round(max(0.0, float(clone['deep_semantic_score']) - diversity_penalty), 5)
        selected.append(clone)
        per_doc[doc] = doc_count + 1
        seen_chunk_windows.add(window)
        if len(selected) >= max(1, top_n):
            break
    selected.sort(key=lambda x: -float(x.get('deep_semantic_score') or 0.0))
    for item in selected:
        item['score'] = max(float(item.get('score') or 0.0), min(1.5, float(item.get('deep_semantic_score') or 0.0)))
    return selected


_ATTRIBUTE_ALIASES: dict[str, tuple[str, ...]] = {
    'طول': ('طول', 'درازا'),
    'عرض': ('عرض', 'پهنا'),
    'ارتفاع': ('ارتفاع', 'بلندی'),
    'وزن': ('وزن', 'ظرفیت وزنی', 'حداکثر بار', 'تناژ'),
    'ظرفیت': ('ظرفیت',),
    'توقف': ('توقف', 'مدت توقف'),
    'کنسلی': ('کنسلی', 'لغو'),
    'انحراف مسیر': ('انحراف مسیر', 'انحراف'),
    'حق مشتری': ('حق مشتری',),
}

def _condition_fragment(sentence: str) -> str:
    n=_norm(sentence)
    starts=[n.find(_norm(marker)) for marker in (_CONDITION_MARKERS+_EXCEPTION_MARKERS) if n.find(_norm(marker))>=0]
    if not starts:
        return ''
    return n[min(starts):][:400]


def _first_unit_number(text: str) -> tuple[str,str] | None:
    values=_numbers(text)
    if not values:
        return None
    value=values[0]
    parts=value.split(' ',1)
    return parts[0], parts[1] if len(parts)>1 else ''


def _typed_numeric_facts(sentence: str, *, source: str, document_id: str, chunk_index: int) -> list[dict[str, Any]]:
    n=_norm(sentence)
    entities=_entities(sentence)
    subject=entities[0] if entities else 'عمومی'
    condition=_condition_fragment(sentence)
    facts: list[dict[str, Any]]=[]
    # Capture each attribute locally. The next 55 characters are enough to bind
    # "طول" to 250 and not accidentally to a later "ارتفاع" value.
    hits: list[tuple[int,str,str]]=[]
    for attribute,aliases in _ATTRIBUTE_ALIASES.items():
        for alias in aliases:
            pos=n.find(_norm(alias))
            if pos>=0:
                hits.append((pos,attribute,_norm(alias)))
    hits.sort()
    for index,(pos,attribute,alias) in enumerate(hits):
        next_pos=hits[index+1][0] if index+1<len(hits) else min(len(n),pos+70)
        segment=n[pos:min(next_pos,pos+70)]
        pair=_first_unit_number(segment)
        if not pair:
            continue
        value,unit=pair
        facts.append({
            'subject':subject,'attribute':attribute,'value':value,'unit':unit,
            'condition':condition,'text':sentence[:900],'source':source,
            'document_id':document_id,'chunk_index':chunk_index,
        })
    return facts

def _sentences(text: str) -> list[str]:
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not text:
        return []
    return [x.strip(' -–—•') for x in re.split(r'(?<=[.!؟؛])\s+|\n+', text) if 8 <= len(x.strip()) <= 900]


def build_rule_exception_map(items: list[dict[str, Any]], *, max_each: int = 12) -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {
        'base_rules': [], 'conditions': [], 'exceptions': [], 'limits': [], 'numeric_facts': [], 'typed_facts': [],
    }
    seen: set[str] = set()
    typed_seen: set[tuple[str,str,str,str,str]] = set()
    for item in items:
        source_name = str(item.get('file_name') or item.get('source_type') or 'منبع')
        document_id=str(item.get('document_id') or '')
        chunk_index=int(item.get('chunk_index') or 0)
        text = str(item.get('content') or item.get('answer') or '')
        for sentence in _sentences(text):
            key = _norm(sentence)
            if key in seen:
                continue
            seen.add(key)
            n = _norm(sentence)
            record = {'text': sentence[:900], 'source': source_name, 'document_id': document_id, 'chunk_index': chunk_index}
            if any(_norm(x) in n for x in _EXCEPTION_MARKERS): categories['exceptions'].append(record)
            if any(_norm(x) in n for x in _CONDITION_MARKERS): categories['conditions'].append(record)
            if any(_norm(x) in n for x in _LIMIT_MARKERS): categories['limits'].append(record)
            if _numbers(sentence): categories['numeric_facts'].append(record)
            if any(_norm(x) in n for x in _RULE_MARKERS) and not any(_norm(x) in n for x in _EXCEPTION_MARKERS): categories['base_rules'].append(record)
            for fact in _typed_numeric_facts(sentence,source=source_name,document_id=document_id,chunk_index=chunk_index):
                fkey=(fact['subject'],fact['attribute'],fact['value'],fact['unit'],fact['condition'])
                if fkey not in typed_seen:
                    typed_seen.add(fkey);categories['typed_facts'].append(fact)
    for key in ('base_rules','conditions','exceptions','limits','numeric_facts'):
        categories[key] = categories[key][:max_each]
    categories['typed_facts']=categories['typed_facts'][:max_each*3]

    # A numeric conflict exists only for the same canonical subject + attribute +
    # condition. Different dimensions (length/width/height) are not conflicts.
    groups: dict[tuple[str,str,str], dict[str, Any]]={}
    for fact in categories['typed_facts']:
        key=(fact['subject'],fact['attribute'],fact['condition'])
        group=groups.setdefault(key,{'values':set(),'facts':[]})
        group['values'].add((fact['value'],fact['unit']))
        group['facts'].append(fact)
    conflicts=[]
    for (subject,attribute,condition),group in groups.items():
        if len(group['values'])>=2:
            conflicts.append({
                'subject':subject,'attribute':attribute,'condition':condition,
                'values':[f"{v} {u}".strip() for v,u in sorted(group['values'])],
                'sources':list(dict.fromkeys(str(f['source']) for f in group['facts']))[:6],
            })
    return {
        **categories,
        'potential_numeric_conflicts': conflicts,
        'has_rule_context': bool(categories['base_rules'] or categories['conditions'] or categories['exceptions'] or categories['limits']),
    }


def format_rule_map_for_prompt(rule_map: dict[str, Any], *, max_chars: int = 7000) -> str:
    labels = (
        ('base_rules','قواعد اصلی'), ('conditions','شرط‌ها'), ('exceptions','استثناها/تبصره‌ها'),
        ('limits','محدودیت‌ها'), ('numeric_facts','اعداد و مقادیر'), ('typed_facts','فکت‌های ساختاریافته'),
    )
    parts: list[str] = []
    used = 0
    for key, label in labels:
        rows = rule_map.get(key) or []
        if not rows:
            continue
        lines = [f"- {row.get('text','')}" for row in rows]
        block = f"{label}:\n" + '\n'.join(lines)
        if used + len(block) > max_chars:
            block = block[:max(0, max_chars-used)]
        if block.strip():
            parts.append(block)
            used += len(block)
        if used >= max_chars:
            break
    return '\n\n'.join(parts)


def evidence_confidence(
    plan: QueryPlan,
    items: list[dict[str, Any]],
    rule_map: dict[str, Any] | None = None,
    *,
    verification_status: str | None = None,
) -> tuple[float, dict[str, float]]:
    if not items:
        return 0.0, {'retrieval':0.0,'coverage':0.0,'alignment':0.0,'rules':0.0,'verification':0.0}
    top = max(float(x.get('deep_semantic_score') or x.get('rerank_score') or x.get('score') or 0.0) for x in items)
    retrieval = max(0.0, min(1.0, top / 0.9))
    coverage = max(float(x.get('query_coverage_score') or 0.0) for x in items)
    entity = max(float(x.get('entity_alignment_score') or 0.0) for x in items) if plan.entities else 0.75
    numeric = max(float(x.get('number_alignment_score') or 0.0) for x in items) if plan.numbers else 0.75
    alignment = (entity + numeric) / 2.0
    rules = 0.72
    rule_map = rule_map or {}
    if 'exception_sensitive' in plan.flags or 'limit_sensitive' in plan.flags or 'conditional' in plan.flags:
        has_needed = bool(rule_map.get('conditions') or rule_map.get('exceptions') or rule_map.get('limits'))
        rules = 1.0 if has_needed else 0.38
    verification = {
        'verified': 1.0,
        'deterministic_verified': 0.94,
        'not_required': 0.82,
        'incomplete': 0.52,
        'provider_unavailable': 0.45,
        'failed': 0.20,
    }.get(str(verification_status or 'not_required'), 0.78)
    score = retrieval*0.40 + coverage*0.16 + alignment*0.16 + rules*0.13 + verification*0.15
    if plan.complexity >= 0.72 and coverage < 0.35:
        score -= 0.08
    score = max(0.0, min(1.0, score))
    return round(score, 4), {
        'retrieval':round(retrieval,4),'coverage':round(coverage,4),'alignment':round(alignment,4),
        'rules':round(rules,4),'verification':round(verification,4),
    }
