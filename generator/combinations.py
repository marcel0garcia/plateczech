"""
Plate combination generators — all are lazy Python generators (yield-based).
Priority order for "rarity": short numeric > short alpha > alphanumeric > words > patterns
"""
import itertools
import string


def numeric_plates(max_digits: int = 7):
    """Pure numeric plates, shortest first: '1', '2', ..., '9', '10', ..."""
    for length in range(1, max_digits + 1):
        start = 10 ** (length - 1) if length > 1 else 0
        end = 10 ** length
        for n in range(start, end):
            yield str(n)


def exact_numeric_plates(digits: int):
    """All zero-padded numeric plates of exactly `digits` length (e.g. 000–999)."""
    for combo in itertools.product(string.digits, repeat=digits):
        yield "".join(combo)


def alpha_plates(min_length: int = 1, max_length: int = 4):
    """Pure alpha plates, shortest first: A, B, ..., Z, AA, AB, ..."""
    for length in range(min_length, max_length + 1):
        for combo in itertools.product(string.ascii_uppercase, repeat=length):
            yield "".join(combo)


def numeric_range_plates(min_digits: int = 1, max_digits: int = 3):
    """Zero-padded numeric plates across a range of digit counts (e.g. 0–9, 00–99, 000–999)."""
    for length in range(min_digits, max_digits + 1):
        yield from exact_numeric_plates(length)


def alphanumeric_plates(max_length: int = 5):
    """Mixed alpha+numeric combos that contain at least one letter and one digit."""
    charset = string.ascii_uppercase + string.digits
    for length in range(2, max_length + 1):
        for combo in itertools.product(charset, repeat=length):
            plate = "".join(combo)
            if any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate):
                yield plate


def word_plates(wordlist_path: str, min_len: int = 3, max_len: int = 5):
    """Yield 3-5 letter dictionary words from a word list file."""
    try:
        with open(wordlist_path) as f:
            for line in f:
                word = line.strip().upper()
                if min_len <= len(word) <= max_len and word.isalpha():
                    yield word
    except FileNotFoundError:
        return


class GeneratorPipeline:
    """
    Chains multiple generators in sequence (mode='chain') or
    interleaves them round-robin (mode='interleave').
    """

    def __init__(self, generators: list, mode: str = "chain"):
        self.generators = generators
        self.mode = mode

    def __iter__(self):
        if self.mode == "chain":
            for gen in self.generators:
                yield from gen
        elif self.mode == "interleave":
            iters = [iter(g) for g in self.generators]
            while iters:
                exhausted = []
                for it in iters:
                    try:
                        yield next(it)
                    except StopIteration:
                        exhausted.append(it)
                for it in exhausted:
                    iters.remove(it)
