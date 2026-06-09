from config import WORDLIST_PATH


def get_words(min_len: int = 3, max_len: int = 5, path: str = WORDLIST_PATH) -> list[str]:
    """Load and filter words from the wordlist file."""
    words = []
    try:
        with open(path) as f:
            for line in f:
                word = line.strip().upper()
                if min_len <= len(word) <= max_len and word.isalpha():
                    words.append(word)
    except FileNotFoundError:
        pass
    return words
