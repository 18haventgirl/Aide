"""Explicit local encoder budgets. Offsets always refer to the original strings.

This counts the pinned BGE tokenizer, not the remote answer model's tokens.
The legacy policy remains available for historical experiment reproduction.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


POLICIES = ("legacy", "query_first_v1")


def tokenizer_fingerprint(directory):
    files = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
             "sentencepiece.bpe.model", "vocab.txt", "config.json")
    hashes = {name: hashlib.sha256((Path(directory)/name).read_bytes()).hexdigest()
              for name in files if (Path(directory)/name).is_file()}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def _ranges(offsets):
    result = []
    for start, end in offsets:
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def _encoded(tokenizer, text, base=0):
    row = tokenizer(text, add_special_tokens=False, truncation=False,
                    return_offsets_mapping=True)
    return list(row["input_ids"]), [(a+base, b+base) for a, b in row["offset_mapping"]]


def _head_tail(ids, offsets, budget):
    if len(ids) <= budget:
        return list(ids), list(offsets)
    head = (budget+1)//2
    tail = budget-head
    return ids[:head]+(ids[-tail:] if tail else []), offsets[:head]+(offsets[-tail:] if tail else [])


def query_parts(query):
    marker = "\n当前问题："
    if query.startswith("用户此前明确陈述：") and marker in query:
        facts, _, current = query.rpartition(marker)
        return current, len(facts)+len(marker), facts[len("用户此前明确陈述："):], len("用户此前明确陈述：")
    return query, 0, "", 0


@dataclass(frozen=True)
class PairBudget:
    max_length: int = 256
    query_max_tokens: int = 64
    title_max_tokens: int = 32
    min_passage_tokens: int = 32

    def __post_init__(self):
        if any(type(n) is not int for n in self.__dict__.values()):
            raise ValueError("token budgets must be integers")
        if not 64 <= self.max_length <= 512:
            raise ValueError("BGE pair length must be between 64 and 512")
        if (self.query_max_tokens < 8 or self.title_max_tokens < 0 or self.min_passage_tokens < 8
                or self.query_max_tokens+self.title_max_tokens+self.min_passage_tokens+4 > self.max_length):
            raise ValueError("query/title/passage budgets exceed pair length")


def prepare_query(tokenizer, query, max_tokens):
    """Prioritize the current question, then the most recent explicit facts."""
    current, base, facts, fact_base = query_parts(query)
    current_ids, current_offsets = _encoded(tokenizer, current, base)
    selected, offsets = _head_tail(current_ids, current_offsets, max_tokens)
    retained_current = len(selected)
    fact_ids, fact_offsets = _encoded(tokenizer, facts, fact_base) if facts else ([], [])
    remaining = max_tokens-len(selected)
    # A real textual separator prevents current/fact words from fusing. Its
    # synthetic tokens receive no original-string offsets.
    separator = tokenizer("；此前：", add_special_tokens=False)["input_ids"]
    fact_budget = max(0, remaining-len(separator))
    if fact_ids and fact_budget:
        chosen = min(fact_budget, len(fact_ids))
        selected += separator+fact_ids[-chosen:]
        offsets += [(0, 0)]*len(separator)+fact_offsets[-chosen:]
    return selected, offsets, {
        "current_question_tokens": len(current_ids), "retained_current_question_tokens": retained_current,
        "current_question_truncated": retained_current < len(current_ids),
        "prior_fact_tokens": len(fact_ids), "retained_prior_fact_tokens": min(fact_budget, len(fact_ids)),
        "query_ranges": _ranges(sorted(offsets)),
    }


def prepare_pair(tokenizer, query, passage, budget=None, policy="query_first_v1"):
    budget = budget or PairBudget()
    if policy not in POLICIES:
        raise ValueError("unknown encoder input policy")
    raw = tokenizer(query, passage, truncation=False, return_offsets_mapping=True)
    if policy == "legacy":
        selected = tokenizer(query, passage, truncation=True, max_length=budget.max_length,
                             return_offsets_mapping=True)
        sequences = selected.sequence_ids()
        offsets = selected.pop("offset_mapping")
        query_ranges = _ranges([span for seq, span in zip(sequences, offsets) if seq == 0])
        passage_ranges = _ranges([span for seq, span in zip(sequences, offsets) if seq == 1])
        model_inputs = dict(selected)
        details = {"query_ranges": query_ranges}
    else:
        query_ids, _, details = prepare_query(tokenizer, query, budget.query_max_tokens)
        special = tokenizer.num_special_tokens_to_add(pair=True)
        available = budget.max_length-special-len(query_ids)
        # Keep the document header within its own budget. The body always gets
        # the remainder; a long title cannot evict a short relevant passage.
        line, newline, body = passage.partition("\n")
        if newline:
            title_ids, title_offsets = _encoded(tokenizer, line)
            title_ids = title_ids[:budget.title_max_tokens]
            title_offsets = title_offsets[:len(title_ids)]
            body_ids, body_offsets = _encoded(tokenizer, body, len(line)+1)
            room = max(0, available-len(title_ids))
            passage_ids = title_ids+body_ids[:room]
            passage_ranges = _ranges(title_offsets+body_offsets[:room])
            details.update(title_tokens=len(_encoded(tokenizer, line)[0]),
                           retained_title_tokens=len(title_ids), retained_body_tokens=min(room, len(body_ids)))
        else:
            ids, offsets = _encoded(tokenizer, passage)
            passage_ids = ids[:available]
            passage_ranges = _ranges(offsets[:available])
        model_inputs = dict(tokenizer.prepare_for_model(query_ids, passage_ids, add_special_tokens=True,
                                                       truncation=False, return_attention_mask=True))
    if len(model_inputs["input_ids"]) > budget.max_length:
        raise ValueError("encoder input exceeded explicit budget")
    return model_inputs, {"policy": policy, "max_length": budget.max_length,
        "raw_pair_tokens": len(raw["input_ids"]), "actual_pair_tokens": len(model_inputs["input_ids"]),
        "special_tokens": tokenizer.num_special_tokens_to_add(pair=True),
        "passage_ranges": passage_ranges, **details}
