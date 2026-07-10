"""Shared STP helpers used by the guided collision-pair search."""

import re


def _rotr(word, amount):
    """Return an STP expression rotating a 32-bit word right."""
    return "(%s[%d:0]@%s[31:%d])" % (word, amount - 1, word, amount)


def _shr(word, amount):
    """Return an STP expression shifting a 32-bit word right."""
    return "(0bin%s@%s[31:%d])" % ("0" * amount, word, amount)


def _xor3(a, b, c):
    return "BVXOR(BVXOR(%s,%s),%s)" % (a, b, c)


def big_sigma0(word):
    return _xor3(_rotr(word, 2), _rotr(word, 13), _rotr(word, 22))


def big_sigma1(word):
    return _xor3(_rotr(word, 6), _rotr(word, 11), _rotr(word, 25))


def small_sigma0(word):
    return _xor3(_rotr(word, 7), _rotr(word, 18), _shr(word, 3))


def small_sigma1(word):
    return _xor3(_rotr(word, 17), _rotr(word, 19), _shr(word, 10))


def ch(e, f, g):
    return "((%s&%s)|((~%s)&%s))" % (e, f, e, g)


def maj(a, b, c):
    return "((%s&%s)|(%s&%s)|(%s&%s))" % (a, b, a, c, b, c)


def hx(value):
    """Format an integer as a 32-bit STP hexadecimal literal."""
    return "0hex%08x" % (value & 0xFFFFFFFF)


def reg_diff(fixed, value_prefix, difference_prefix, step):
    """Return the XOR mask and signed source bits for one DC register.

    ``fixed`` contains the signed-difference encoding (v, d).  An active bit
    has d=1; v fixes the corresponding bit in the first execution (n -> 0,
    u -> 1).
    """
    names = [
        (
            "%s_%d_%d" % (value_prefix, step, bit),
            "%s_%d_%d" % (difference_prefix, step, bit),
        )
        for bit in range(32)
    ]
    present = [
        bit
        for bit, (value_name, difference_name) in enumerate(names)
        if value_name in fixed or difference_name in fixed
    ]
    if present and len(present) != 32:
        raise ValueError(
            "Incomplete signed DC word %s/%s at step %d"
            % (value_prefix, difference_prefix, step)
        )

    mask = 0
    signed_bits = {}
    for bit in range(32):
        value_name, difference_name = names[bit]
        value = fixed.get(value_name, 0)
        difference = fixed.get(difference_name, 0)
        if (value, difference) not in ((0, 0), (0, 1), (1, 1)):
            raise ValueError(
                "Invalid signed difference (%d,%d) for %s/%s step %d bit %d"
                % (
                    value,
                    difference,
                    value_prefix,
                    difference_prefix,
                    step,
                    bit,
                )
            )
        if difference == 0:
            continue
        mask |= 1 << bit
        signed_bits[bit] = value
    return mask, signed_bits


def has_reg_diff(fixed, value_prefix, difference_prefix, step):
    """Return whether the DC contains this signed 32-bit register/word."""
    return any(
        "%s_%d_%d" % (value_prefix, step, bit) in fixed
        or "%s_%d_%d" % (difference_prefix, step, bit) in fixed
        for bit in range(32)
    )


def word_diff(fixed, step):
    return reg_diff(fixed, "wv", "wd", step)


_ASSIGNMENT = re.compile(
    r"([A-Za-z0-9_]+)\s*=\s*0(x|hex|bin)([0-9a-fA-F]+)"
)


def load_words(text):
    """Parse STP counterexample assignments into ``{name: integer}``."""
    assignments = {}
    for line in text.splitlines():
        match = _ASSIGNMENT.search(line)
        if not match:
            continue
        kind, digits = match.group(2), match.group(3)
        assignments[match.group(1)] = int(
            digits,
            2 if kind == "bin" else 16,
        )
    return assignments
