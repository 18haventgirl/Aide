"""Small offline character n-gram embedding for development preview only."""

import hashlib
import math
import re


class ChineseHashEmbedding:
    dimensions = 512

    def name(self):
        return "aide-medical-local-hash-zh-v1"

    def __call__(self, input):
        output = []
        for text in input:
            chars = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text.lower())
            terms = chars + [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
            vector = [0.0] * self.dimensions
            for term in terms:
                slot = int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest(), "big") % self.dimensions
                vector[slot] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            output.append([value / norm for value in vector])
        return output
